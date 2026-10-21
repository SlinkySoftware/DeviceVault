<template>
  <q-page class="q-pa-md">
    <q-card>
      <q-card-section>
        <div class="row items-center q-mb-sm">
          <div class="col">
            <div class="text-h5">Worker Dashboard</div>
          </div>
          <div class="col-auto">
            <q-btn color="primary" icon="refresh" label="Refresh" :loading="loading" @click="loadWorkers" />
          </div>
        </div>
        <div class="row justify-end">
          <div class="text-caption text-grey">
            Registered collection/storage workers, queue bindings, and liveliness state
          </div>
        </div>
      </q-card-section>
      <q-separator />

      <q-card-section>
        <q-table
          :rows="workers"
          :columns="columns"
          row-key="worker_id"
          flat
          :loading="loading"
          class="admin-table"
        >
          <template v-slot:body-cell-status="props">
            <q-td :props="props">
              <q-badge :color="props.row.is_online ? 'positive' : 'negative'" :label="props.row.status.toUpperCase()" />
            </q-td>
          </template>

          <template v-slot:body-cell-worker_name="props">
            <q-td :props="props">
              <div class="text-weight-medium">{{ props.row.worker_name }}</div>
              <div class="text-caption text-grey">{{ props.row.worker_id }}</div>
            </q-td>
          </template>

          <template v-slot:body-cell-queues="props">
            <q-td :props="props">
              <div class="row q-gutter-xs">
                <q-badge
                  v-for="queue in props.row.queues"
                  :key="`${props.row.worker_id}-${queue}`"
                  color="primary"
                  outline
                >
                  {{ queue }}
                </q-badge>
                <span v-if="!props.row.queues || props.row.queues.length === 0" class="text-grey">—</span>
              </div>
            </q-td>
          </template>

          <template v-slot:body-cell-last_seen_at="props">
            <q-td :props="props">
              <div>{{ formatDateTimeShort(props.row.last_seen_at) || '—' }}</div>
              <div class="text-caption text-grey">{{ formatRelativeTime(props.row.last_seen_at) || '—' }}</div>
            </q-td>
          </template>

          <template v-slot:body-cell-last_pong_at="props">
            <q-td :props="props">
              <div>{{ formatDateTimeShort(props.row.last_pong_at) || '—' }}</div>
              <div class="text-caption text-grey">{{ formatRelativeTime(props.row.last_pong_at) || '—' }}</div>
            </q-td>
          </template>
        </q-table>

        <div class="text-caption text-grey q-mt-sm">
          Online timeout: {{ onlineTimeoutSeconds }}s • Probe grace: {{ pongGraceSeconds }}s
        </div>
      </q-card-section>
    </q-card>
  </q-page>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import api from '../services/api'
import { formatDateTimeShort, formatRelativeTime } from '../utils/timezone'

const $q = useQuasar()
const workers = ref([])
const loading = ref(false)
const refreshTimer = ref(null)
const onlineTimeoutSeconds = ref(90)
const pongGraceSeconds = ref(45)

const columns = [
  { name: 'status', label: 'Status', field: 'status', align: 'left', sortable: true },
  { name: 'worker_name', label: 'Worker', field: 'worker_name', align: 'left', sortable: true },
  { name: 'worker_type', label: 'Type', field: 'worker_type', align: 'left', sortable: true },
  { name: 'hostname', label: 'Host', field: 'hostname', align: 'left', sortable: true },
  { name: 'pid', label: 'PID', field: 'pid', align: 'left', sortable: true },
  { name: 'queues', label: 'Queues', field: 'queues', align: 'left' },
  { name: 'last_seen_at', label: 'Last Seen', field: 'last_seen_at', align: 'left', sortable: true },
  { name: 'last_pong_at', label: 'Last Probe Reply', field: 'last_pong_at', align: 'left', sortable: true },
]

async function loadWorkers() {
  loading.value = true
  try {
    const response = await api.get('/worker-registry/')
    workers.value = response.data?.workers || []
    onlineTimeoutSeconds.value = response.data?.online_timeout_seconds || 90
    pongGraceSeconds.value = response.data?.pong_grace_seconds || 45
  } catch (error) {
    $q.notify({ type: 'negative', message: 'Failed to load worker registry' })
  } finally {
    loading.value = false
  }
}

function startAutoRefresh() {
  stopAutoRefresh()
  refreshTimer.value = setInterval(() => {
    loadWorkers()
  }, 10000)
}

function stopAutoRefresh() {
  if (refreshTimer.value) {
    clearInterval(refreshTimer.value)
    refreshTimer.value = null
  }
}

onMounted(() => {
  loadWorkers()
  startAutoRefresh()
})

onBeforeUnmount(() => {
  stopAutoRefresh()
})
</script>
