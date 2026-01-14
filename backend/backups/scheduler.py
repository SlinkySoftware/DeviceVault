"""
Backup Scheduler Daemon
Periodically checks for scheduled backups and enqueues device collection tasks.
Handles missed backup windows on restart using configurable time window.
"""

# DeviceVault - A comprehensive network device backup management application with web interface for user and admin access and backend component for automated backup collection.
# Copyright (C) 2026, Slinky Software
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os
import sys
import time
import json
import logging
import signal
from datetime import datetime, timedelta
from typing import Optional

# Setup Django environment
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'devicevault.settings')
django.setup()

from django.utils import timezone
from django.db import transaction
from redis import Redis
import yaml

from celery_app import app as celery_app, REDIS_URL
from core.models import SchedulerState
from policies.models import BackupSchedule
from devices.models import Device, DeviceBackupResult
from core.timezone_utils import get_display_timezone, local_to_utc, utc_to_local
from devicevault_worker import collection_queue_name_from_group

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger('devicevault.scheduler')

# Redis client for distributed locking
redis_client = Redis.from_url(REDIS_URL)

# Global flag for graceful shutdown
shutdown_requested = False


class SchedulerDaemon:
    """
    Scheduler daemon that periodically checks for due backups and enqueues them.
    Uses Redis distributed lock to prevent multiple scheduler instances.
    """
    
    def __init__(self):
        self.config = self.load_config()
        self.enabled = self.config.get('enabled', True)
        self.restart_window_minutes = self.config.get('restart_window_minutes', 120)
        self.tick_interval = 60  # Check every 60 seconds
        self.lock = None
        self.lock_key = 'devicevault:scheduler:lock'
        self.lock_timeout = 180  # Lock expires after 180 seconds (3 minutes) if not renewed
        self.is_running = False
        
        logger.info(f"Scheduler initialized: enabled={self.enabled}, restart_window={self.restart_window_minutes}min, lock_timeout={self.lock_timeout}s")
    
    def load_config(self) -> dict:
        """Load scheduler configuration from config.yaml"""
        config_path = os.environ.get('DEVICEVAULT_CONFIG', 'config/config.yaml')
        
        if not os.path.exists(config_path):
            logger.warning(f"Config file not found: {config_path}, using defaults")
            return {'enabled': True, 'restart_window_minutes': 120}
        
        try:
            with open(config_path, 'r') as f:
                cfg = yaml.safe_load(f) or {}
                return cfg.get('scheduler', {'enabled': True, 'restart_window_minutes': 120})
        except Exception as exc:
            logger.exception(f"Failed to load config from {config_path}")
            return {'enabled': True, 'restart_window_minutes': 120}
    
    def acquire_lock(self) -> bool:
        """Acquire Redis distributed lock to ensure single scheduler instance"""
        try:
            # Check for stale locks first
            if self.check_stale_lock():
                logger.info("Cleared stale lock from dead process, retrying acquisition")
            
            # Use SET with NX (only set if not exists) and EX (expiry)
            acquired = redis_client.set(
                self.lock_key,
                os.getpid(),
                nx=True,
                ex=self.lock_timeout
            )
            if acquired:
                logger.info(f"Acquired scheduler lock (PID: {os.getpid()})")
                self.is_running = True
                return True
            else:
                existing_pid = redis_client.get(self.lock_key)
                logger.warning(f"Failed to acquire lock, held by PID: {existing_pid}")
                return False
        except Exception as exc:
            logger.exception("Error acquiring Redis lock")
            return False
    
    def renew_lock(self) -> bool:
        """Renew the Redis lock to prevent expiry during operation"""
        try:
            # Only renew if we still hold the lock (check PID matches)
            current_holder = redis_client.get(self.lock_key)
            if current_holder and int(current_holder) == os.getpid():
                redis_client.expire(self.lock_key, self.lock_timeout)
                return True
            else:
                logger.error(f"Lost scheduler lock! Current holder: {current_holder}, our PID: {os.getpid()}")
                return False
        except Exception as exc:
            logger.exception("Error renewing Redis lock")
            return False
    
    def release_lock(self):
        """Release the Redis distributed lock immediately"""
        try:
            # Check if we still hold the lock
            current_holder = redis_client.get(self.lock_key)
            if current_holder and int(current_holder) == os.getpid():
                # Delete immediately and also set a short TTL as backup
                pipe = redis_client.pipeline()
                pipe.delete(self.lock_key)
                pipe.execute()
                logger.info("Released scheduler lock")
            else:
                logger.warning(f"Lock held by different PID: {current_holder}, our PID: {os.getpid()}")
        except Exception as exc:
            logger.exception("Error releasing Redis lock")
    
    def check_stale_lock(self) -> bool:
        """
        Check if lock is held by a dead process and force-release if necessary.
        Returns True if lock was stale and cleared, False otherwise.
        """
        try:
            current_holder = redis_client.get(self.lock_key)
            if not current_holder:
                return False
            
            holder_pid = int(current_holder)
            
            # Check if the process is still alive (only works on Unix systems)
            try:
                os.kill(holder_pid, 0)  # Signal 0 checks if process exists
                return False  # Process is alive
            except (OSError, ProcessLookupError):
                # Process is dead, release stale lock
                logger.warning(f"Detected stale lock held by dead PID {holder_pid}, clearing it")
                redis_client.delete(self.lock_key)
                return True
        except Exception as exc:
            logger.warning(f"Error checking for stale lock: {exc}")
            return False
    
    def calculate_next_run(self, schedule: BackupSchedule, from_time: Optional[datetime] = None) -> datetime:
        """
        Calculate the next execution time for a schedule in display timezone.
        
        Args:
            schedule: BackupSchedule instance
            from_time: Calculate from this time (UTC), or use now if None
        
        Returns:
            Next execution time as naive datetime in display timezone
        """
        if from_time is None:
            from_time = timezone.now()
        
        # Convert UTC to display timezone
        display_tz = get_display_timezone()
        current_display = utc_to_local(from_time)
        
        if schedule.schedule_type == 'daily':
            # Next occurrence of hour:minute today or tomorrow
            next_run = current_display.replace(
                hour=schedule.hour,
                minute=schedule.minute,
                second=0,
                microsecond=0
            )
            if next_run <= current_display:
                next_run += timedelta(days=1)
        
        elif schedule.schedule_type == 'weekly':
            # Next occurrence of day_of_week at hour:minute
            target_dow = int(schedule.day_of_week)  # 0=Sunday, 6=Saturday
            current_dow = (current_display.weekday() + 1) % 7  # Convert Monday=0 to Sunday=0
            
            days_ahead = (target_dow - current_dow) % 7
            next_run = current_display.replace(
                hour=schedule.hour,
                minute=schedule.minute,
                second=0,
                microsecond=0
            ) + timedelta(days=days_ahead)
            
            # If it's the same day but time has passed, move to next week
            if days_ahead == 0 and next_run <= current_display:
                next_run += timedelta(days=7)
        
        elif schedule.schedule_type == 'monthly':
            # Next occurrence of day_of_month at hour:minute
            next_run = current_display.replace(
                day=schedule.day_of_month,
                hour=schedule.hour,
                minute=schedule.minute,
                second=0,
                microsecond=0
            )
            if next_run <= current_display:
                # Move to next month
                if next_run.month == 12:
                    next_run = next_run.replace(year=next_run.year + 1, month=1)
                else:
                    next_run = next_run.replace(month=next_run.month + 1)
        
        else:
            # Custom cron or unknown type - default to next day at configured time
            logger.warning(f"Schedule {schedule.id} has unsupported type {schedule.schedule_type}, defaulting to daily")
            next_run = current_display.replace(
                hour=schedule.hour,
                minute=schedule.minute,
                second=0,
                microsecond=0
            )
            if next_run <= current_display:
                next_run += timedelta(days=1)
        
        return next_run
    
    def is_backup_due(self, schedule: BackupSchedule, current_time: datetime) -> bool:
        """
        Check if a backup is due to run now.
        
        Args:
            schedule: BackupSchedule instance
            current_time: Current UTC time
        
        Returns:
            True if backup should execute now
        """
        # Calculate next run from last_run_at or from current time
        if schedule.last_run_at:
            next_run_display = self.calculate_next_run(schedule, schedule.last_run_at)
        else:
            # Never run before - check if it's time now
            next_run_display = self.calculate_next_run(schedule, current_time - timedelta(days=1))
        
        # Convert next_run to UTC for comparison
        next_run_utc = local_to_utc(next_run_display)
        
        # Backup is due if current_time >= next_run_utc
        return current_time >= next_run_utc
    
    def process_missed_backups(self, scheduler_state: SchedulerState):
        """
        On startup, check for missed backups and either execute or mark as failed.
        
        Args:
            scheduler_state: Current scheduler state with last_tick
        """
        if not scheduler_state.last_tick:
            logger.info("No previous tick time, skipping missed backup processing")
            return
        
        now = timezone.now()
        last_tick = scheduler_state.last_tick
        restart_cutoff = now - timedelta(minutes=self.restart_window_minutes)
        
        logger.info(f"Processing missed backups between {last_tick} and {now}")
        logger.info(f"Restart window cutoff: {restart_cutoff}")
        
        schedules = BackupSchedule.objects.filter(enabled=True)
        
        for schedule in schedules:
            # Get all devices with this schedule
            devices = Device.objects.filter(
                backup_schedule=schedule,
                enabled=True
            ).select_related('credential', 'collection_group', 'device_group')
            
            if not devices.exists():
                continue
            
            # Check each potential missed execution between last_tick and now
            check_time = last_tick
            while check_time < now:
                next_run_display = self.calculate_next_run(schedule, check_time)
                next_run_utc = local_to_utc(next_run_display)
                
                # If this execution time is in the past (between last_tick and now)
                if last_tick < next_run_utc <= now:
                    if next_run_utc >= restart_cutoff:
                        # Within restart window - execute the backup
                        logger.info(f"Executing missed backup for schedule '{schedule.name}' at {next_run_utc}")
                        for device in devices:
                            self.enqueue_device_backup(device, schedule, is_catchup=True)
                    else:
                        # Outside restart window - mark as missed
                        logger.warning(f"Marking missed backup for schedule '{schedule.name}' at {next_run_utc}")
                        for device in devices:
                            self.create_missed_backup_result(device, schedule, next_run_utc, now)
                
                # Move check_time forward to next potential execution
                check_time = next_run_utc + timedelta(seconds=1)
                
                # Safety: don't check more than 365 days worth
                if (now - check_time).days > 365:
                    break
    
    def create_missed_backup_result(self, device: Device, schedule: BackupSchedule, scheduled_time: datetime, detected_time: datetime):
        """
        Create a DeviceBackupResult record marking a missed backup window.
        
        Args:
            device: Device that missed backup
            schedule: Schedule that was missed
            scheduled_time: When backup was supposed to run (UTC)
            detected_time: When the miss was detected (UTC)
        """
        try:
            task_identifier = f'missed:{device.id}:{scheduled_time.isoformat()}'
            log_message = {
                'level': 'ERROR',
                'message': f'Missed backup window for schedule "{schedule.name}"',
                'scheduled_time': scheduled_time.isoformat(),
                'detected_time': detected_time.isoformat(),
                'reason': 'Scheduler was not running during scheduled time'
            }
            
            DeviceBackupResult.objects.create(
                task_id=f'missed_{device.id}_{int(scheduled_time.timestamp())}',
                task_identifier=task_identifier,
                device=device,
                status='missed_window',
                timestamp=detected_time,
                log=json.dumps([log_message])
            )
            logger.info(f"Created missed backup result for device {device.name}")
        except Exception as exc:
            logger.exception(f"Failed to create missed backup result for device {device.name}")
    
    def enqueue_device_backup(self, device: Device, schedule: BackupSchedule, is_catchup: bool = False):
        """
        Enqueue a device backup task via Celery.
        
        Args:
            device: Device to backup
            schedule: Schedule triggering the backup
            is_catchup: Whether this is a catch-up from missed window
        """
        try:
            task_type = 'scheduled_catchup' if is_catchup else 'scheduled'
            task_identifier = f'{task_type}:{device.id}:{timezone.now().isoformat()}'
            
            cfg = {
                'device_id': device.id,
                'task_identifier': task_identifier,
                'ip': device.ip_address,
                'credentials': device.credential.data if device.credential else {},
                'backup_method': device.backup_method,
                'plugin_params': {},
                'timeout': 240
            }
            
            # Determine queue based on collection group
            queue = None
            if device.collection_group:
                queue_name = collection_queue_name_from_group(device.collection_group)
                if queue_name:
                    queue = queue_name
            
            task = celery_app.send_task('device.collect', args=[json.dumps(cfg)], queue=queue)
            logger.info(f"Enqueued backup for device {device.name} (schedule: {schedule.name}, task_id: {task.id}, queue: {queue})")
        except Exception as exc:
            logger.exception(f"Failed to enqueue backup for device {device.name}")
    
    def process_schedules(self):
        """Main scheduler tick - check all enabled schedules and enqueue due backups"""
        try:
            now = timezone.now()
            schedules = BackupSchedule.objects.filter(enabled=True)
            
            logger.debug(f"Processing {schedules.count()} enabled schedules")
            
            for schedule in schedules:
                # Check if this schedule is due to run
                if not self.is_backup_due(schedule, now):
                    continue
                
                logger.info(f"Schedule '{schedule.name}' is due to run")
                
                # Get all devices with this schedule
                devices = Device.objects.filter(
                    backup_schedule=schedule,
                    enabled=True
                ).select_related('credential', 'collection_group', 'device_group')
                
                device_count = devices.count()
                if device_count == 0:
                    logger.info(f"Schedule '{schedule.name}' has no enabled devices")
                    continue
                
                logger.info(f"Enqueuing {device_count} devices for schedule '{schedule.name}'")
                
                # Enqueue backup for each device
                for device in devices:
                    self.enqueue_device_backup(device, schedule, is_catchup=False)
                
                # Update schedule's last_run_at and calculate next_run_at
                schedule.last_run_at = now
                schedule.next_run_at = local_to_utc(self.calculate_next_run(schedule, now))
                schedule.save(update_fields=['last_run_at', 'next_run_at'])
                
                logger.info(f"Updated schedule '{schedule.name}' - next run at {schedule.next_run_at}")
            
        except Exception as exc:
            logger.exception("Error processing schedules")
    
    def update_scheduler_state(self, scheduler_state: SchedulerState):
        """Update SchedulerState with current tick time and status"""
        try:
            scheduler_state.last_tick = timezone.now()
            scheduler_state.is_running = True
            scheduler_state.scheduler_pid = os.getpid()
            scheduler_state.save(update_fields=['last_tick', 'is_running', 'scheduler_pid'])
        except Exception as exc:
            logger.exception("Failed to update scheduler state")
    
    def run(self):
        """Main scheduler loop"""
        if not self.enabled:
            logger.info("Scheduler is disabled in config, exiting")
            return
        
        # Acquire distributed lock
        if not self.acquire_lock():
            logger.error("Failed to acquire scheduler lock, another instance may be running")
            return
        
        try:
            # Load or create scheduler state
            scheduler_state = SchedulerState.load()
            scheduler_state.last_restart_at = timezone.now()
            scheduler_state.save(update_fields=['last_restart_at'])
            
            # Process missed backups from last run
            self.process_missed_backups(scheduler_state)
            
            logger.info(f"Scheduler started, tick interval: {self.tick_interval}s")
            
            last_tick_time = time.time()
            
            while not shutdown_requested:
                try:
                    # Renew lock to prevent expiry
                    if not self.renew_lock():
                        logger.error("Lost scheduler lock, exiting")
                        break
                    
                    # Process schedules
                    self.process_schedules()
                    
                    # Update scheduler state
                    self.update_scheduler_state(scheduler_state)
                    
                    # Sleep until next tick
                    current_time = time.time()
                    elapsed = current_time - last_tick_time
                    sleep_time = max(0, self.tick_interval - elapsed)
                    
                    if sleep_time > 0:
                        time.sleep(sleep_time)
                    
                    last_tick_time = time.time()
                    
                except Exception as exc:
                    logger.exception("Error in scheduler main loop")
                    time.sleep(self.tick_interval)
            
            logger.info("Scheduler stopped gracefully")
            
        finally:
            # Mark scheduler as not running and release lock
            try:
                scheduler_state = SchedulerState.load()
                scheduler_state.is_running = False
                scheduler_state.save(update_fields=['is_running'])
            except:
                pass
            
            self.release_lock()


def main():
    """Entry point for scheduler daemon"""
    def shutdown_handler(signum, frame):
        """Handle shutdown signals gracefully"""
        global shutdown_requested
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        shutdown_requested = True
    
    # Register signal handlers for clean shutdown
    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)
    
    logger.info("DeviceVault Backup Scheduler starting...")
    
    scheduler = SchedulerDaemon()
    try:
        scheduler.run()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        # Ensure lock is released on any exit
        logger.info("Performing final cleanup...")
        scheduler.release_lock()
        logger.info("Scheduler cleanup complete")
    
    logger.info("DeviceVault Backup Scheduler exited")
    return 0


if __name__ == '__main__':
    # Check for command-line arguments
    if len(sys.argv) > 1:
        if sys.argv[1] == '--clear-lock':
            # Force clear the scheduler lock (useful for recovery)
            try:
                lock_key = 'devicevault:scheduler:lock'
                current = redis_client.get(lock_key)
                if current:
                    redis_client.delete(lock_key)
                    logger.info(f"Cleared scheduler lock (was held by PID {current})")
                    print(f"✓ Cleared scheduler lock")
                else:
                    logger.info("No scheduler lock found")
                    print("ℹ No scheduler lock found")
            except Exception as exc:
                logger.exception("Error clearing lock")
                print(f"✗ Error clearing lock: {exc}")
                sys.exit(1)
            sys.exit(0)
        elif sys.argv[1] == '--check-lock':
            # Check lock status
            try:
                lock_key = 'devicevault:scheduler:lock'
                current = redis_client.get(lock_key)
                if current:
                    pid = int(current)
                    # Try to check if process is alive
                    try:
                        os.kill(pid, 0)
                        print(f"🔒 Lock held by PID {pid} (process is alive)")
                    except (OSError, ProcessLookupError):
                        print(f"⚠️  Lock held by dead PID {pid} (stale lock)")
                else:
                    print("🔓 No scheduler lock held")
            except Exception as exc:
                logger.exception("Error checking lock")
                print(f"✗ Error checking lock: {exc}")
                sys.exit(1)
            sys.exit(0)
        else:
            print(f"Unknown option: {sys.argv[1]}")
            print("Usage: python -m backups.scheduler [--clear-lock|--check-lock]")
            sys.exit(1)
    
    sys.exit(main())
