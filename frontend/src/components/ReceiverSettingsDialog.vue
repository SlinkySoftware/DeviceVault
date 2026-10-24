<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- A push receiver's settings: what it listens on and how devices log in. -->
<template>
  <FormDialog v-model="open" :title="`Receiver settings · ${worker?.name ?? ''}`" :saving="saving" width="640px" @submit="submit">
    <q-inner-loading :showing="loading" />
    <template v-if="!loading && worker">
      <q-banner v-if="hostKey" dense rounded class="bg-subtle">
        <template #avatar><q-icon name="key" color="primary" /></template>
        SSH host key devices should pin:
        <div class="fingerprint q-mt-xs">{{ hostKey }}</div>
      </q-banner>

      <q-input
        v-model.trim="form.bind_address"
        outlined
        label="Listen address (optional)"
        hint="An address of the receiver's host; empty listens on every address"
      />
      <q-input
        v-model.number="maxFileSizeMib"
        type="number"
        outlined
        label="Largest accepted file (MiB)"
        :rules="[(v: number) => (Number.isInteger(v) && v >= 1) || 'At least 1 MiB']"
      />

      <q-separator />
      <q-toggle v-model="form.ssh_enabled" label="Accept SCP and SFTP uploads" />
      <template v-if="form.ssh_enabled">
        <q-input
          v-model.number="form.ssh_port"
          type="number"
          outlined
          label="SSH port"
          hint="Ports below 1024 need extra host setup (see DEPLOYMENT.md)"
          :rules="[(v: number) => (Number.isInteger(v) && v >= 1 && v <= 65535) || 'A port from 1 to 65535']"
        />
        <q-input
          v-model.trim="form.ssh_username"
          outlined
          label="Username devices log in with"
          :rules="[(v: string) => !!v || 'A username is required']"
        />
        <q-input
          v-model="password"
          type="password"
          outlined
          autocomplete="new-password"
          :label="settings?.ssh_password_set ? 'New password (leave empty to keep the current one)' : 'Password'"
        />
        <q-checkbox v-if="settings?.ssh_password_set" v-model="removePassword" label="Remove the password (keys only)" />
        <q-input
          v-model="form.ssh_authorized_keys"
          type="textarea"
          outlined
          autogrow
          label="Authorised public keys (optional)"
          hint="One OpenSSH public key per line, e.g. ssh-ed25519 AAAA… comment"
        />
        <div class="text-caption text-grey">
          A device must also be set to push over SCP/SFTP, and connect from its own IP address.
        </div>
      </template>

      <q-separator />
      <q-toggle v-model="form.tftp_enabled" label="Accept TFTP uploads" />
      <template v-if="form.tftp_enabled">
        <q-input
          v-model.number="form.tftp_port"
          type="number"
          outlined
          label="TFTP port (UDP)"
          hint="69 is the standard port; ports below 1024 need extra host setup (see DEPLOYMENT.md)"
          :rules="[(v: number) => (Number.isInteger(v) && v >= 1 && v <= 65535) || 'A port from 1 to 65535']"
        />
        <q-banner dense rounded class="bg-warning text-black">
          TFTP has no login: only devices explicitly set to push over TFTP are accepted, by their address alone,
          which can be forged on networks that do not filter spoofed traffic.
        </q-banner>
      </template>
    </template>
  </FormDialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { workersApi } from '@/api/endpoints'
import type { ReceiverSettings, ReceiverSettingsWrite, Worker } from '@/api/types'
import FormDialog from '@/components/FormDialog.vue'
import { useNotify } from '@/composables/useNotify'

const props = defineProps<{ worker: Worker | null }>()

const open = defineModel<boolean>({ required: true })

const emit = defineEmits<{ saved: [] }>()

const MIB = 1024 * 1024

const notify = useNotify()
const loading = ref(false)
const saving = ref(false)
const settings = ref<ReceiverSettings | null>(null)
const form = ref<ReceiverSettingsWrite>(blank())
const password = ref('')
const removePassword = ref(false)

const hostKey = computed(
  () =>
    props.worker?.runtime.receiver?.host_key_fingerprint ??
    props.worker?.capabilities.receiver?.host_key_fingerprint ??
    '',
)
const maxFileSizeMib = computed({
  get: () => Math.round(form.value.max_file_size / MIB),
  set: (value: number) => (form.value.max_file_size = value * MIB),
})

function blank(): ReceiverSettingsWrite {
  return {
    bind_address: '',
    max_file_size: 512 * MIB,
    ssh_enabled: false,
    ssh_port: 2222,
    ssh_username: 'devicevault',
    ssh_authorized_keys: '',
    tftp_enabled: false,
    tftp_port: 6969,
  }
}

watch(open, async (isOpen) => {
  if (!isOpen || !props.worker) return
  loading.value = true
  password.value = ''
  removePassword.value = false
  try {
    const current = await workersApi.receiverSettings(props.worker.id)
    settings.value = current
    form.value = {
      bind_address: current.bind_address ?? '',
      max_file_size: current.max_file_size,
      ssh_enabled: current.ssh_enabled,
      ssh_port: current.ssh_port,
      ssh_username: current.ssh_username,
      ssh_authorized_keys: current.ssh_authorized_keys,
      tftp_enabled: current.tftp_enabled,
      tftp_port: current.tftp_port,
    }
  } catch (error) {
    notify.error(error, 'Failed to load the receiver settings')
    open.value = false
  } finally {
    loading.value = false
  }
})

async function submit(): Promise<void> {
  if (!props.worker) return
  const body: ReceiverSettingsWrite = { ...form.value, bind_address: form.value.bind_address || null }
  if (password.value) body.ssh_password = password.value
  else if (removePassword.value) body.ssh_password = ''
  saving.value = true
  try {
    await workersApi.updateReceiverSettings(props.worker.id, body)
    notify.success(`${props.worker.name} updated`)
    open.value = false
    emit('saved')
  } catch (error) {
    notify.error(error, 'Failed to save the receiver settings')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.fingerprint {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  word-break: break-all;
}
</style>
