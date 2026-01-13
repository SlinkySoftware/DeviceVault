# Timezone Handling Implementation

## Overview
DeviceVault now has comprehensive timezone handling that ensures all database timestamps are stored in UTC while displaying times in a configurable application timezone.

## Key Principles

1. **Database Storage**: All timestamps in the database are stored in UTC
2. **Log Entries**: All log entries from workers use UTC timestamps
3. **Display**: All user-facing displays use the configured application timezone
4. **Time-Bound Queries**: Queries like "last 24 hours" use the configured timezone for boundaries
5. **Backup Schedules**: Schedules are authored and displayed in local time, executed in local time, but stored as UTC

## Configuration

### Backend Configuration
The timezone is configured in `backend/config/config.yaml`:

```yaml
# Application timezone - used for display and scheduling
# All times are stored in UTC in the database
# Valid timezone names: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones
timezone: Australia/Sydney
```

Valid timezone names follow the IANA Time Zone Database format (e.g., 'America/New_York', 'Europe/London', 'Asia/Tokyo').

### Django Settings
In `backend/devicevault/settings.py`:

```python
# Application timezone for display - read from config.yaml
DEVICEVAULT_DISPLAY_TIMEZONE = cfg.get('timezone', 'Australia/Sydney')

# Django timezone - always UTC for database storage
TIME_ZONE = 'UTC'
USE_TZ = True
```

## Backend Implementation

### Timezone Utilities (`backend/core/timezone_utils.py`)

Key functions:

- `get_display_timezone()` - Returns the configured timezone object
- `utc_now()` - Get current time in UTC
- `local_now()` - Get current time in display timezone
- `utc_to_local(dt)` - Convert UTC datetime to display timezone
- `local_to_utc(dt)` - Convert display timezone datetime to UTC
- `get_time_bounds_24h()` - Get UTC bounds for "last 24 hours" in local time
- `get_time_bounds_days(days)` - Get UTC bounds for last N days in local time
- `get_day_bounds_local(date)` - Get start/end of day in local timezone as UTC
- `format_datetime_local(dt)` - Format datetime in display timezone
- `parse_local_datetime(dt_str)` - Parse local datetime string to UTC

### API Updates

**Dashboard Stats (`/api/dashboard-stats/`)**:
- Uses `get_time_bounds_24h()` for "last 24 hours" calculation
- Uses `get_day_bounds_local()` for daily chart boundaries
- Returns `timezone` field with configured timezone name

**Timezone Config (`/api/timezone/`)**:
- New endpoint that returns the configured timezone
- Used by frontend to fetch timezone configuration

**Recent Backup Activity (`/api/recent-backup-activity/`)**:
- Returns timestamps in ISO 8601 format with UTC timezone
- Frontend handles conversion to local timezone

### Worker Logs
Workers in `backend/devicevault_worker.py` use UTC:

```python
datetime.utcnow().isoformat() + 'Z'
```

The 'Z' suffix explicitly indicates UTC timezone.

## Frontend Implementation

### Timezone Utilities (`frontend/src/utils/timezone.js`)

Key functions:

- `getAppTimezone()` - Fetch configured timezone from backend
- `utcToLocal(utcIsoString)` - Convert UTC ISO string to local Date
- `formatDateTime(utcIsoString, options)` - Format as local datetime
- `formatDate(utcIsoString, options)` - Format as local date
- `formatRelativeTime(utcIsoString)` - Format as relative time ("5m ago")
- `formatDateTimeShort(utcIsoString)` - Format as short datetime
- `localToUtc(localDate)` - Convert local Date to UTC ISO string

### Component Updates

All date/time displays have been updated:

1. **Dashboard.vue**
   - Activity timestamps use `formatRelativeTime()` for intuitive display
   - Chart boundaries respect local timezone
   
2. **ViewBackups.vue**
   - Backup timestamps formatted in local timezone
   - Sorting uses proper date comparison
   
3. **Devices.vue**
   - Last backup time formatted in local timezone
   
4. **EditDevice.vue**
   - Backup timestamps formatted in local timezone
   
5. **CompareBackups.vue**
   - Comparison timestamps formatted in local timezone
   - Date sorting uses local timezone
   
6. **DeviceGroups.vue**
   - Created/updated dates formatted in local timezone

## Migration Guide

### For Existing Installations

1. **Update Configuration**:
   ```bash
   # Edit backend/config/config.yaml and add:
   timezone: Your/Timezone  # e.g., America/New_York
   ```

2. **Restart Services**:
   ```bash
   ./devicevault.sh restart
   ```

3. **Verify**:
   - Check dashboard shows times in your local timezone
   - Check API endpoint: `curl http://localhost:8000/api/timezone/`
   - Verify "last 24 hours" calculations align with local time

### For New Installations

The default timezone is `Australia/Sydney`. Edit `backend/config/config.yaml` before first run to set your timezone.

## Testing Timezone Handling

### Backend Tests

```python
# Test timezone utilities
from core.timezone_utils import get_timezone_name, local_now, utc_to_local
from django.utils import timezone

# Check configured timezone
print(f"Timezone: {get_timezone_name()}")  # Should show your configured TZ

# Test time conversion
utc_time = timezone.now()
local_time = utc_to_local(utc_time)
print(f"UTC: {utc_time}, Local: {local_time}")

# Test time bounds
from core.timezone_utils import get_time_bounds_24h
start, end = get_time_bounds_24h()
print(f"Last 24h: {start} to {end}")  # Should be in UTC but represent 24h local
```

### Frontend Tests

Open browser console:

```javascript
import { formatDateTime, formatRelativeTime } from './utils/timezone'

// Test formatting
const utcTime = new Date().toISOString()
console.log('UTC:', utcTime)
console.log('Formatted:', formatDateTime(utcTime))
console.log('Relative:', formatRelativeTime(utcTime))
```

## Troubleshooting

### Times Show Wrong Offset

**Problem**: Times display with incorrect offset (e.g., +13 instead of +11).

**Solution**: 
1. Check `backend/config/config.yaml` - ensure timezone is correct
2. Restart backend: `./devicevault.sh restart`
3. Clear browser cache and reload frontend

### "Last 24 Hours" Shows Wrong Data

**Problem**: Dashboard "last 24 hours" metric doesn't match expected data.

**Solution**:
1. Verify timezone is configured correctly
2. Check that `get_time_bounds_24h()` is being used in API views
3. Ensure database has `USE_TZ = True` in settings

### Worker Logs Show Wrong Time

**Problem**: Worker logs show incorrect timestamps.

**Solution**: Worker logs should ALWAYS be in UTC. This is intentional. They are not converted to local time. If they show non-UTC times, verify `datetime.utcnow()` is being used.

## Future Enhancements

1. **User-Specific Timezones**: Allow each user to set their own timezone preference
2. **Schedule Builder UI**: Visual schedule builder that shows local time
3. **Timezone Warnings**: Display warnings when timezone changes affect scheduled backups
4. **Historical Timezone Changes**: Track when timezone configuration changes

## Related Files

- `backend/config/config.yaml` - Timezone configuration
- `backend/devicevault/settings.py` - Django timezone settings
- `backend/core/timezone_utils.py` - Backend timezone utilities
- `backend/api/views.py` - API endpoints with timezone handling
- `frontend/src/utils/timezone.js` - Frontend timezone utilities
- All Vue components in `frontend/src/pages/` - Date/time display

## API Reference

### GET /api/timezone/

Returns the configured application timezone.

**Response**:
```json
{
  "timezone": "Australia/Sydney"
}
```

### GET /api/dashboard-stats/

Returns dashboard statistics with timezone information.

**Response includes**:
```json
{
  ...
  "timezone": "Australia/Sydney",
  "dailyStats": [...]
}
```

All timestamps in responses are ISO 8601 format with UTC timezone indicator (Z suffix).
