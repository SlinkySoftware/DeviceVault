<template>
  <q-page class="q-pa-md">
    <div class="text-h4 q-mb-md">Backups</div>
    
    <q-card class="q-mb-md">
      <q-card-section>
        <div class="row q-col-gutter-md">
          <div class="col-12 col-md-5">
            <q-input
              v-model="a"
              label="Path A"
              outlined
            />
          </div>
          <div class="col-12 col-md-5">
            <q-input
              v-model="b"
              label="Path B"
              outlined
            />
          </div>
          <div class="col-12 col-md-2">
            <q-btn
              color="primary"
              label="Compare"
              @click="compare"
              :loading="loading"
              style="width: 100%"
            />
          </div>
        </div>
      </q-card-section>
    </q-card>

    <q-card v-if="diff">
      <q-card-section>
        <div class="text-h6 q-mb-md">Diff Results</div>
        <pre class="bg-grey-2 q-pa-md" style="overflow: auto">{{ diff }}</pre>
      </q-card-section>
    </q-card>
  </q-page>
</template>

<script setup>
import { ref } from 'vue'
import { useQuasar } from 'quasar'
import api from '../services/api'

const $q = useQuasar()
const a = ref('')
const b = ref('')
const diff = ref('')
const loading = ref(false)

async function compare() {
  loading.value = true
  try {
    const r = await api.post('/backups/compare/', { 
      a_path: a.value, 
      b_path: b.value 
    })
    diff.value = r.data.diff
  } catch (error) {
    $q.notify({
      type: 'negative',
      message: 'Failed to compare backups'
    })
  } finally {
    loading.value = false
  }
}
</script>
