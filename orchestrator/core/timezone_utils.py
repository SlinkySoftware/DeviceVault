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

"""
Timezone utility functions for DeviceVault.

This module provides utilities for handling timezone conversions between UTC (database storage)
and the configured application timezone (display and user interactions).

Key principles:
- All database timestamps are stored in UTC
- All log entries use UTC
- All user-facing displays use the configured timezone
- Time-bound queries (e.g., "last 24 hours") use the configured timezone for boundary calculation
"""

from datetime import datetime, timedelta
from django.utils import timezone
from django.conf import settings
import pytz


def get_display_timezone():
    """
    Get the configured display timezone for the application.
    
    Returns:
        pytz.timezone: The timezone object for display purposes
    """
    tz_name = getattr(settings, 'DEVICEVAULT_DISPLAY_TIMEZONE', 'UTC')
    return pytz.timezone(tz_name)


def utc_now():
    """
    Get current time in UTC (timezone-aware).
    
    Returns:
        datetime: Current UTC time
    """
    return timezone.now()


def local_now():
    """
    Get current time in the configured display timezone.
    
    Returns:
        datetime: Current time in display timezone
    """
    return utc_now().astimezone(get_display_timezone())


def utc_to_local(dt):
    """
    Convert UTC datetime to display timezone.
    
    Args:
        dt: datetime object (timezone-aware or naive)
        
    Returns:
        datetime: DateTime in display timezone
    """
    if dt is None:
        return None
    
    # If naive, assume UTC
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, pytz.UTC)
    
    return dt.astimezone(get_display_timezone())


def local_to_utc(dt):
    """
    Convert display timezone datetime to UTC.
    
    Args:
        dt: datetime object in display timezone
        
    Returns:
        datetime: DateTime in UTC
    """
    if dt is None:
        return None
    
    # If naive, assume display timezone
    if timezone.is_naive(dt):
        dt = get_display_timezone().localize(dt)
    
    return dt.astimezone(pytz.UTC)


def get_time_bounds_24h():
    """
    Get time bounds for "last 24 hours" based on display timezone.
    
    This ensures that "last 24 hours" means the last 24 hours in local time,
    which is more intuitive for users.
    
    Returns:
        tuple: (start_time_utc, end_time_utc) - both as timezone-aware UTC datetimes
    """
    local_end = local_now()
    local_start = local_end - timedelta(hours=24)
    
    return local_to_utc(local_start), local_to_utc(local_end)


def get_time_bounds_days(days):
    """
    Get time bounds for last N days based on display timezone.
    
    Args:
        days (int): Number of days to look back
        
    Returns:
        tuple: (start_time_utc, end_time_utc) - both as timezone-aware UTC datetimes
    """
    local_end = local_now()
    local_start = local_end - timedelta(days=days)
    
    return local_to_utc(local_start), local_to_utc(local_end)


def get_day_bounds_local(date):
    """
    Get start and end of a specific day in display timezone, returned as UTC.
    
    Args:
        date: datetime or date object
        
    Returns:
        tuple: (day_start_utc, day_end_utc) - both as timezone-aware UTC datetimes
    """
    tz = get_display_timezone()
    
    # Convert to date if datetime
    if isinstance(date, datetime):
        date = date.date()
    
    # Create start and end of day in local timezone
    day_start = tz.localize(datetime.combine(date, datetime.min.time()))
    day_end = tz.localize(datetime.combine(date, datetime.max.time()))
    
    return day_start.astimezone(pytz.UTC), day_end.astimezone(pytz.UTC)


def format_datetime_local(dt, format_str='%Y-%m-%d %H:%M:%S %Z'):
    """
    Format a datetime in the display timezone.
    
    Args:
        dt: datetime object (timezone-aware or naive UTC)
        format_str: strftime format string
        
    Returns:
        str: Formatted datetime string
    """
    if dt is None:
        return ''
    
    local_dt = utc_to_local(dt)
    return local_dt.strftime(format_str)


def parse_local_datetime(dt_str, format_str='%Y-%m-%d %H:%M:%S'):
    """
    Parse a datetime string as local time and convert to UTC.
    
    Args:
        dt_str: datetime string
        format_str: strptime format string
        
    Returns:
        datetime: Timezone-aware UTC datetime
    """
    tz = get_display_timezone()
    naive_dt = datetime.strptime(dt_str, format_str)
    local_dt = tz.localize(naive_dt)
    return local_dt.astimezone(pytz.UTC)


def get_timezone_name():
    """
    Get the configured timezone name.
    
    Returns:
        str: Timezone name (e.g., 'Australia/Sydney')
    """
    return getattr(settings, 'DEVICEVAULT_DISPLAY_TIMEZONE', 'UTC')
