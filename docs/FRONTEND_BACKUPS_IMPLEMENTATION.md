# DeviceVault Frontend: Backups Page Implementation

## Summary

Implemented a fully functional backups page for the DeviceVault frontend that replaces the placeholder UI. The implementation includes:

- Backup list display with date/time, selection radio buttons, and action buttons
- A/B backup selection logic with mutual exclusion
- Modal dialog for viewing backup content
- Backup download functionality with proper filename formatting
- Comparison page for side-by-side backup viewing
- Full API integration with proper error handling and loading states

## Files Changed

### 1. **frontend/src/pages/ViewBackups.vue** (Replaced entirely)

**Features:**
- Displays list of stored backups for a device, sorted newest → oldest
- QTable with columns:
  - **A** — Radio button to select backup A
  - **B** — Radio button to select backup B (independent group)
  - **Date/Time** — Human-readable timestamp
  - **Backend** — Storage backend type (git/fs)
  - **Status** — Success/failure badge
  - **Actions** — View and Download buttons

**Radio Button Logic:**
- Two independent radio groups: one for A, one for B
- Allows exactly one backup as A and one as B
- Prevents selecting the same backup as both A and B (handled by separate v-model refs)

**Compare Button:**
- Disabled until both A and B are selected
- Routes to `/devices/{id}/backups/compare?backup_a=X&backup_b=Y`
- Includes loading state during navigation

**View Modal:**
- Opens maximized Quasar dialog
- Displays backup ID and timestamp
- Shows content in monospace font with scrollable container
- Preserves line breaks and spacing
- Handles errors gracefully

**Download:**
- Filename format: `{devicename}_{backupid}_{YYYYMMDD-HHMMSS}.txt`
- Uses data URL with encodeURIComponent for content encoding
- Triggers browser native download

**API Integration:**
- `GET /api/stored-backups/?device={device_id}` — List backups
- `GET /api/devices/{device_id}/` — Get device name
- `GET /api/stored-backups/{backup_id}/download/` — Download content
  - Uses `responseType: 'text'` for plain text response handling

**Error Handling:**
- Loading spinner during data fetch
- User-friendly error notifications via Quasar
- Empty state message when no backups exist

### 2. **frontend/src/pages/CompareBackups.vue** (New)

**Features:**
- Side-by-side display of two backup contents
- Each side shows backup ID and timestamp
- Content displayed in monospace font with scrollable containers
- "Back to Backups" button for navigation
- Parallel loading of both backups for performance

**API Integration:**
- `GET /api/stored-backups/{backup_id}/` — Get backup metadata
- `GET /api/stored-backups/{backup_id}/download/` — Get backup content
  - Uses `responseType: 'text'` for plain text response handling

**Error Handling:**
- Loading spinner during initial fetch
- Error message displayed if backups fail to load
- Graceful handling of missing query parameters

### 3. **frontend/src/router/index.js** (Updated)

**Changes:**
- Added import for `CompareBackups` component
- Added new route: `/devices/:id/backups/compare`
  - Component: `CompareBackups`
  - Meta: `{ requiresAuth: true }`

## Code Patterns & Conventions

### Vue 3 Composition API
- Used `ref()` for reactive state
- Used `computed()` for derived values (device ID)
- Used `onMounted()` for initialization

### Quasar Components
- `QPage` — Page wrapper
- `QCard` — Container
- `QTable` — Backup list with custom cell templates
- `QRadio` — A/B selection (two independent groups)
- `QBtn` — Action buttons
- `QDialog` — View modal (maximized)
- `QSpinner` — Loading indicator
- `QBadge` — Status display
- `q-notify()` — User notifications

### API Calls
- Used axios instance from `frontend/src/services/api.js`
- Proper error handling with try/catch
- `responseType: 'text'` for endpoint returning plain text
- Token authentication handled by interceptor

### Filename Formatting
```javascript
// Format: YYYYMMDD-HHMMSS
const dateTime = `${year}${month}${day}-${hours}${minutes}${seconds}`
const filename = `${deviceName}_${backupId}_${dateTime}.txt`
```

## User Experience Flow

1. **View Backups List**
   - User clicks "Backups" button on a device
   - Page loads with backup list sorted newest → oldest
   - Loading spinner shown during fetch

2. **Select Backups for Comparison**
   - User clicks radio buttons to select backup A
   - User clicks radio buttons to select backup B
   - "Compare Selected" button becomes enabled

3. **Compare Backups**
   - User clicks "Compare Selected"
   - Routes to comparison page
   - Both backups displayed side-by-side
   - User can scroll independently through each backup

4. **View Single Backup**
   - User clicks "View" button
   - Modal opens with full backup content
   - Content is scrollable and uses monospace font

5. **Download Backup**
   - User clicks "Download" button
   - Browser downloads file with properly formatted filename
   - Success notification shown

## API Expectations

Backend should provide:

- `GET /api/stored-backups/` — List endpoint with optional `device` filter parameter
- `GET /api/stored-backups/{backup_id}/` — Retrieve metadata
- `GET /api/stored-backups/{backup_id}/download/` — Return plain text (Content-Type: text/plain)
- `GET /api/devices/{device_id}/` — Get device details

All endpoints require authentication token (automatically injected by api.js interceptor).

## Testing Notes

### Manual Testing Checklist
- [ ] Navigate to device backups page
- [ ] Verify backup list loads and displays in reverse chronological order
- [ ] Select backup A via radio button
- [ ] Select backup B via radio button (different backup)
- [ ] Verify Compare button is enabled
- [ ] Click Compare button and verify navigation works
- [ ] On comparison page, verify both backups display content
- [ ] Click "Back to Backups" and verify navigation
- [ ] Click "View" on a backup and verify modal opens
- [ ] Verify modal content is scrollable and readable
- [ ] Click "Download" and verify file downloads with correct name
- [ ] Test error states (API failures, missing device, etc.)

## Future Enhancements

Possible improvements (not implemented per requirements):
- Diff highlighting between backups
- Filter/search backups by date range
- Backup details sidebar (size, storage backend, etc.)
- Bulk download multiple backups
- Restore from backup button (would require additional backend endpoint)
