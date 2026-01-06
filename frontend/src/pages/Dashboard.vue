<template>
  <q-page class="q-pa-md">
    <div class="text-h4 q-mb-md">Dashboard</div>
    
    <div class="row q-col-gutter-md q-mb-md">
      <div class="col-12 col-md-3">
        <q-card class="stat-card">
          <q-card-section>
            <div class="text-h6">Configured Devices</div>
            <div class="row q-col-gutter-sm q-mt-sm">
              <div class="col-5">
                <div class="nested-box strong-box">
                  <div class="text-subtitle1 text-weight-medium">Total</div>
                  <div class="text-h5 text-primary text-weight-medium">{{ totalDevices }}</div>
                </div>
              </div>
              <div class="col-7">
                <div class="nested-box" v-for="(count, type) in stats.devicesByType" :key="type">
                  <div class="text-body1 text-weight-medium">{{ type }}</div>
                  <div class="text-caption text-grey">{{ count }} devices</div>
                </div>
                <div v-if="Object.keys(stats.devicesByType || {}).length === 0" class="text-caption text-grey">No devices yet</div>
              </div>
            </div>
          </q-card-section>
        </q-card>
      </div>
      
      <div class="col-12 col-md-3">
        <q-card class="stat-card">
          <q-card-section>
            <div class="text-h6">Backups (24h)</div>
            <div class="row q-col-gutter-sm q-mt-sm">
              <div class="col-6">
                <div class="nested-box bg-green-1 text-positive">
                  <div class="text-subtitle1 text-weight-medium">{{ stats.success24h }}</div>
                  <div class="text-caption text-weight-medium">Success</div>
                </div>
              </div>
              <div class="col-6">
                <div class="nested-box bg-red-1 text-negative">
                  <div class="text-subtitle1 text-weight-medium">{{ stats.failed24h }}</div>
                  <div class="text-caption text-weight-medium">Failed</div>
                </div>
              </div>
            </div>
          </q-card-section>
        </q-card>
      </div>
      
      <div class="col-12 col-md-3">
        <q-card class="stat-card">
          <q-card-section>
            <div class="text-h6">Avg Backup Time</div>
            <div class="text-h4 text-primary">{{ stats.avgDuration }}s</div>
          </q-card-section>
        </q-card>
      </div>

      <div class="col-12 col-md-3">
        <q-card class="stat-card">
          <q-card-section>
            <div class="text-h6">Success Rate</div>
            <div class="text-h4 text-positive">
              {{ successRate }}%
            </div>
          </q-card-section>
        </q-card>
      </div>
    </div>

    <div class="row q-col-gutter-md q-mb-md">
      <div class="col-12 col-md-8">
        <q-card>
          <q-card-section>
            <div class="text-h6 q-mb-md">Backup Success Rate (Last 7 Days)</div>
            <div class="chart-container" style="height: 300px">
              <canvas ref="chartCanvas"></canvas>
            </div>
          </q-card-section>
        </q-card>
      </div>

      <div class="col-12 col-md-4">
        <q-card>
          <q-card-section>
            <div class="text-h6">Recent Activity</div>
          </q-card-section>
          <q-list separator>
            <q-item v-for="item in recentActivity" :key="item.id">
              <q-item-section>
                <q-item-label>{{ item.action }}</q-item-label>
                <q-item-label caption>{{ item.resource }}</q-item-label>
                <q-item-label caption>{{ formatDate(item.created_at) }}</q-item-label>
              </q-item-section>
            </q-item>
            <q-item v-if="recentActivity.length === 0">
              <q-item-section>
                <q-item-label caption>No recent activity</q-item-label>
              </q-item-section>
            </q-item>
          </q-list>
        </q-card>
      </div>
    </div>
  </q-page>
</template>

<script setup>
import { ref, onMounted, computed, nextTick } from 'vue'
import api from '../services/api'

const stats = ref({ 
  devicesByType: {}, 
  success24h: 0, 
  failed24h: 0, 
  avgDuration: 0,
  dailyStats: []
})
const recentActivity = ref([])
const chartCanvas = ref(null)
let chart = null

const successRate = computed(() => {
  const total = stats.value.success24h + stats.value.failed24h
  return total > 0 ? Math.round((stats.value.success24h / total) * 100) : 0
})

const totalDevices = computed(() => {
  return Object.values(stats.value.devicesByType || {}).reduce((a, b) => a + b, 0)
})

function formatDate(dateStr) {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  return date.toLocaleString()
}

async function loadData() {
  try {
    const [statsResp, activityResp] = await Promise.all([
      api.get('/dashboard-stats/'),
      api.get('/audit-logs/?limit=10')
    ])
    stats.value = statsResp.data
    recentActivity.value = Array.isArray(activityResp.data) ? activityResp.data : activityResp.data.results || []
    
    await nextTick()
    renderChart()
  } catch (error) {
    console.error('Failed to load dashboard data:', error)
  }
}

function renderChart() {
  if (!chartCanvas.value) return
  
  // Simple chart rendering (you can replace with Chart.js or other library)
  const ctx = chartCanvas.value.getContext('2d')
  const width = chartCanvas.value.width = chartCanvas.value.offsetWidth
  const height = chartCanvas.value.height = chartCanvas.value.offsetHeight
  
  ctx.clearRect(0, 0, width, height)
  
  const dailyStats = stats.value.dailyStats || []
  if (dailyStats.length === 0) return
  
  const padding = 40
  const chartWidth = width - padding * 2
  const chartHeight = height - padding * 2
  const barWidth = chartWidth / dailyStats.length
  
  // Draw bars
  dailyStats.forEach((day, index) => {
    const x = padding + index * barWidth
    const barH = (day.rate / 100) * chartHeight
    const y = height - padding - barH
    
    ctx.fillStyle = day.rate >= 80 ? '#21BA45' : day.rate >= 50 ? '#F2C037' : '#C10015'
    ctx.fillRect(x + 5, y, barWidth - 10, barH)
    
    // Label
    ctx.fillStyle = '#000'
    ctx.font = '10px sans-serif'
    ctx.textAlign = 'center'
    const label = new Date(day.date).toLocaleDateString('en-US', { weekday: 'short' })
    ctx.fillText(label, x + barWidth / 2, height - padding + 20)
    ctx.fillText(`${Math.round(day.rate)}%`, x + barWidth / 2, y - 5)
  })
  
  // Draw axes
  ctx.strokeStyle = '#ccc'
  ctx.beginPath()
  ctx.moveTo(padding, height - padding)
  ctx.lineTo(width - padding, height - padding)
  ctx.moveTo(padding, padding)
  ctx.lineTo(padding, height - padding)
  ctx.stroke()
}

onMounted(() => {
  loadData()
})
</script>

<style scoped>
.chart-container {
  position: relative;
}
canvas {
  width: 100%;
  height: 100%;
}
.stat-card {
  min-height: 220px;
  display: flex;
  flex-direction: column;
}
.nested-box {
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  padding: 8px 10px;
  background: #fafafa;
}
.strong-box {
  background: #eef3ff;
  border-color: #c5d2ff;
}
.bg-green-1 { background-color: #e8f5e9; }
.bg-red-1 { background-color: #ffebee; }
</style>
