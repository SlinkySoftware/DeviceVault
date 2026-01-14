"""
Backup Schedule Signals
Handles automatic recalculation of next_run_at when schedules are modified.
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

import logging
from datetime import datetime, timedelta
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from policies.models import BackupSchedule
from core.timezone_utils import get_display_timezone, local_to_utc, utc_to_local

logger = logging.getLogger(__name__)


def calculate_next_run(schedule: BackupSchedule) -> datetime:
    """
    Calculate the next execution time for a schedule.
    
    Args:
        schedule: BackupSchedule instance
    
    Returns:
        Next execution time as UTC datetime
    """
    now_utc = timezone.now()
    display_tz = get_display_timezone()
    current_display = utc_to_local(now_utc)
    
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
        try:
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
        except ValueError:
            # Day doesn't exist in current month (e.g., day 31 in February)
            logger.warning(f"Invalid day {schedule.day_of_month} for monthly schedule {schedule.id}")
            # Default to first day of next month
            if current_display.month == 12:
                next_run = current_display.replace(year=current_display.year + 1, month=1, day=1)
            else:
                next_run = current_display.replace(month=current_display.month + 1, day=1)
    
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
    
    # Convert back to UTC
    return local_to_utc(next_run)


@receiver(post_save, sender=BackupSchedule)
def update_schedule_next_run(sender, instance, created, **kwargs):
    """
    Automatically recalculate next_run_at when a schedule is created or modified.
    """
    # Avoid recursion - if this is already saving with next_run_at, skip
    update_fields = kwargs.get('update_fields')
    if not created and update_fields is not None and 'next_run_at' in update_fields:
        return
    
    try:
        next_run_utc = calculate_next_run(instance)
        
        # Update next_run_at field without triggering another post_save
        BackupSchedule.objects.filter(pk=instance.pk).update(next_run_at=next_run_utc)
        
        logger.info(f"Updated schedule '{instance.name}' next_run_at to {next_run_utc}")
    except Exception as exc:
        logger.exception(f"Failed to calculate next_run_at for schedule {instance.id}")
