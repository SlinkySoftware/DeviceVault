<template>
  <q-page class="q-pa-md">
    <q-card>
      <q-card-section>
        <div class="row items-center q-mb-md">
          <div class="col">
            <div class="text-h5">Scheduled Backups Calendar</div>
            <div class="text-caption text-grey">Next 30 days of scheduled device backups</div>
          </div>
          <div class="col-auto">
            <q-btn 
              color="primary" 
              icon="refresh" 
              label="Refresh" 
              @click="loadCalendarData"
              :loading="loading"
            />
          </div>
        </div>
      </q-card-section>

      <q-separator />

      <q-card-section>
        <div v-if="loading" class="text-center q-pa-lg">
          <q-spinner color="primary" size="50px" />
        </div>

        <div v-else-if="Object.keys(calendarData).length === 0" class="text-center q-pa-lg text-grey">
          <p>No scheduled backups found in the next 30 days</p>
        </div>

        <div v-else class="calendar-container">
          <!-- Calendar Header -->
          <div class="calendar-header">
            <div class="calendar-month-label">
              Upcoming Scheduled Backups (Next 30 Days)
            </div>
          </div>

          <!-- Calendar Table -->
          <q-table
            :rows="calendarRows"
            :columns="calendarColumns"
            row-key="date"
            flat
            :pagination.sync="pagination"
            class="schedule-calendar-table"
            hide-pagination
          >
            <template v-slot:body-cell-date="props">
              <q-td :props="props" class="calendar-date-cell">
                <div class="date-number">{{ props.row.formattedDate }}</div>
              </q-td>
            </template>

            <template v-slot:body-cell-schedules="props">
              <q-td :props="props" class="calendar-schedules-cell">
                <div 
                  v-for="schedule in props.row.schedules" 
                  :key="`${props.row.date}-${schedule.schedule_id}`"
                  class="schedule-badge q-mb-xs"
                >
                  <div class="schedule-info">
                    <div class="schedule-name">{{ schedule.schedule_name }}</div>
                    <div class="schedule-time">{{ schedule.time }}</div>
                  </div>
                  <q-badge 
                    :label="`${schedule.device_count} device${schedule.device_count !== 1 ? 's' : ''}`"
                    color="primary"
                    class="device-count-badge"
                  />
                  
                  <q-tooltip max-width="400px" class="device-tooltip">
                    <div v-if="schedule.devices.length > 0" class="device-list">
                      <div class="text-weight-bold q-mb-sm">Devices:</div>
                      <div 
                        v-for="device in schedule.devices" 
                        :key="device.id"
                        class="device-item"
                      >
                        {{ device.name }} - {{ device.ip_address }}
                      </div>
                    </div>
                    <div v-else class="text-grey">
                      No devices with access permissions
                    </div>
                  </q-tooltip>
                </div>
              </q-td>
            </template>
          </q-table>
        </div>
      </q-card-section>
    </q-card>
  </q-page>
</template>

<script>
import api from 'src/services/api'
import { date } from 'quasar'

export default {
  name: 'ScheduleCalendar',
  data() {
    return {
      loading: false,
      calendarData: {},
      autoRefreshInterval: null,
      pagination: {
        rowsPerPage: 0 // Show all rows
      },
      calendarColumns: [
        { name: 'date', label: 'Date', field: 'date', align: 'left', style: 'width: 100px' },
        { name: 'schedules', label: 'Scheduled Backups', field: 'schedules', align: 'left' }
      ]
    }
  },
  computed: {
    calendarRows() {
      const rows = []
      const dataObj = this.calendarData
      
      if (!dataObj || Object.keys(dataObj).length === 0) {
        return rows
      }
      
      // Sort dates and create row for each date (show all dates, not just current month)
      const sortedDates = Object.keys(dataObj).sort()
      
      for (const dateStr of sortedDates) {
        const [year, month, day] = dateStr.split('-').map(Number)
        const dateObj = new Date(year, month - 1, day)
        
        // Sort schedules by time (chronologically)
        const sortedSchedules = [...dataObj[dateStr]].sort((a, b) => {
          return a.time.localeCompare(b.time)
        })
        
        rows.push({
          date: dateStr,
          dateObj: dateObj,
          schedules: sortedSchedules,
          formattedDate: date.formatDate(dateObj, 'ddd DD MMM')
        })
      }
      
      return rows
    }
  },
  methods: {
    async loadCalendarData() {
      try {
        this.loading = true
        const response = await api.get('/scheduled-backups/calendar/')
        this.calendarData = response.data
      } catch (error) {
        console.error('Failed to load calendar data:', error)
        this.$q.notify({
          type: 'negative',
          message: 'Failed to load scheduled backups calendar',
          position: 'top'
        })
      } finally {
        this.loading = false
      }
    },

  },
  mounted() {
    this.loadCalendarData()
    
    // Auto-refresh every 5 minutes
    this.autoRefreshInterval = setInterval(() => {
      this.loadCalendarData()
    }, 5 * 60 * 1000)
  },
  beforeUnmount() {
    if (this.autoRefreshInterval) {
      clearInterval(this.autoRefreshInterval)
    }
  }
}
</script>

<style scoped lang="scss">
.calendar-container {
  background-color: inherit;
  border-radius: 4px;
}

.calendar-header {
  padding: 16px;
  border-bottom: 1px solid var(--q-dark-page, #e0e0e0);
}

.calendar-month-label {
  font-size: 18px;
  font-weight: 500;
  text-align: center;
}

.schedule-calendar-table {
  :deep(.q-table__card) {
    box-shadow: none;
  }

  :deep(.q-table__grid) {
    grid-auto-rows: auto;
  }
}

.calendar-date-cell {
  background-color: var(--q-color-secondary);
  min-width: 120px;
  font-weight: 500;
  vertical-align: top;
  position: sticky;
  left: 0;
  z-index: 1;
}

.date-number {
  font-size: 14px;
  font-weight: 600;
}

.calendar-schedules-cell {
  padding: 12px !important;
  vertical-align: top;
}

.schedule-badge {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background-color: var(--q-dark);
  border: 1px solid var(--q-primary);
  border-left: 3px solid var(--q-primary);
  border-radius: 4px;
  gap: 12px;
  max-width: 420px;
}

.schedule-info {
  flex: 1;
  min-width: 0;
}

.schedule-name {
  font-weight: 600;
  font-size: 14px;
}

.schedule-time {
  font-size: 11px;
  opacity: 0.7;
  font-weight: 500;
}

.device-count-badge {
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
  padding: 4px 10px;
}

.device-tooltip {
  :deep(.q-tooltip) {
    background-color: #2a2a2a !important;
  }
}

.device-list {
  padding: 8px 0;
}

.device-item {
  padding: 6px 0;
  line-height: 1.5;
  white-space: nowrap;
}
</style>
