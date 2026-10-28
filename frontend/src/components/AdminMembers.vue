<script setup lang="ts">
import { Check, Copy, Send, UserPlus } from "@lucide/vue";
import { computed, onMounted, ref } from "vue";

import { ApiError, api } from "@/api/client";
import { MEMBER_ROLES, type CreatedInvitation, type Invitation, type Member, type MemberRole } from "@/api/types";
import { useToasts } from "@/composables/useToasts";
import { formatDate, formatRelative } from "@/lib/format";
import { reloadAt } from "@/lib/navigate";

// The workspace's members and invitations. Admins manage editors, viewers and
// admins; only a signed-in owner makes or changes owners (the server says so too).
const props = defineProps<{ myRole: MemberRole | null; myUserId: number | null }>();
// A member or an invitation changed: the audit log has a new event.
const emit = defineEmits<{ changed: [] }>();

const ROLE_HELP: Record<MemberRole, string> = {
  owner: "Everything, and the owners",
  admin: "Everything but the owners",
  editor: "Upload, change and ask",
  viewer: "Search and ask",
};

const toasts = useToasts();
const members = ref<Member[]>([]);
const invitations = ref<Invitation[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);

const email = ref("");
const role = ref<MemberRole>("editor");
const inviting = ref(false);
const created = ref<CreatedInvitation | null>(null);
const copied = ref(false);

const isOwner = computed(() => props.myRole === "owner");
// Roles this user may give: an owner any, others all but owner.
const givable = computed(() => MEMBER_ROLES.filter((r) => isOwner.value || r !== "owner"));

const message = (caught: unknown) => (caught instanceof ApiError ? caught.message : undefined);
const expired = (invitation: Invitation) => new Date(invitation.expires_at).getTime() <= Date.now();

async function load() {
  try {
    [members.value, invitations.value] = await Promise.all([api.members(), api.invitations()]);
    error.value = null;
  } catch (caught) {
    error.value = message(caught) ?? "The members could not be loaded.";
  } finally {
    loading.value = false;
  }
}
onMounted(load);

function canChange(member: Member) {
  return isOwner.value || member.role !== "owner";
}

async function changeRole(member: Member, event: Event) {
  const select = event.target as HTMLSelectElement;
  const next = select.value as MemberRole;
  try {
    await api.changeRole(member.id, next);
    toasts.success("Role changed", `${member.name} is now ${next}.`);
    emit("changed");
  } catch (caught) {
    select.value = member.role;
    toasts.error("The role could not be changed", message(caught));
  }
  await load();
}

async function removeMember(member: Member) {
  const self = member.id === props.myUserId;
  const warning = self ? " This is you: you leave the workspace." : "";
  if (!window.confirm(`Remove ${member.name} (${member.email}) from the workspace?${warning}`)) return;
  try {
    await api.removeMember(member.id);
    toasts.success("Member removed", `${member.name} can no longer open this workspace.`);
    emit("changed");
    if (self) reloadAt("/");
    else await load();
  } catch (caught) {
    toasts.error("The member could not be removed", message(caught));
  }
}

async function invite() {
  if (!email.value.trim() || inviting.value) return;
  inviting.value = true;
  try {
    created.value = await api.invite(email.value.trim(), role.value);
    copied.value = false;
    email.value = "";
    emit("changed");
    await load();
  } catch (caught) {
    toasts.error("The invitation could not be made", message(caught));
  } finally {
    inviting.value = false;
  }
}

async function copy() {
  if (!created.value) return;
  try {
    await navigator.clipboard.writeText(created.value.link);
    copied.value = true;
  } catch {
    toasts.error("Copying failed", "Select the link and copy it by hand.");
  }
}

async function revoke(invitation: Invitation) {
  if (!window.confirm(`Revoke the invitation for ${invitation.email}? Its link stops working at once.`)) return;
  try {
    await api.revokeInvitation(invitation.id);
    toasts.success("Invitation revoked", `The link for ${invitation.email} no longer works.`);
    if (created.value?.id === invitation.id) created.value = null;
    emit("changed");
    await load();
  } catch (caught) {
    toasts.error("The invitation could not be revoked", message(caught));
  }
}
</script>

<template>
  <section class="members" aria-labelledby="members-title">
    <div>
      <h3 id="members-title">Members</h3>
      <p class="muted small">
        The people who sign in to this workspace, and what their role lets them do. Invite someone with a link: it works
        once, for a week, and only for the email you invite.
      </p>
    </div>

    <form class="invite card" @submit.prevent="invite">
      <label class="field email">
        <span>Email</span>
        <input v-model="email" class="input" type="email" maxlength="254" placeholder="grace@example.com" required />
      </label>
      <label class="field">
        <span>Role</span>
        <select v-model="role" class="select">
          <option v-for="r in givable" :key="r" :value="r">{{ r }} – {{ ROLE_HELP[r] }}</option>
        </select>
      </label>
      <button type="submit" class="btn btn-primary" :disabled="inviting || !email.trim()">
        <UserPlus :size="15" /> Invite
      </button>
    </form>

    <div v-if="created" class="alert alert-success created" role="status">
      <Send :size="18" />
      <div class="created-body">
        <strong>
          {{ created.email }} is invited as {{ created.role }}.
          {{ created.emailed ? "The link is on its way by email; you can send it yourself too." : "Send them this link: it is not shown again." }}
        </strong>
        <div class="secret">
          <code class="mono" data-testid="invitation-link">{{ created.link }}</code>
          <button type="button" class="btn btn-sm" @click="copy">
            <component :is="copied ? Check : Copy" :size="14" /> {{ copied ? "Copied" : "Copy" }}
          </button>
        </div>
      </div>
      <button type="button" class="btn btn-ghost btn-sm" @click="created = null">Done</button>
    </div>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-else-if="loading" class="skeleton table-skeleton" />
    <template v-else>
      <div class="table-wrap card">
        <table class="table">
          <caption class="visually-hidden">Members</caption>
          <thead>
            <tr>
              <th scope="col">Member</th>
              <th scope="col">Role</th>
              <th scope="col" class="hide-sm">Last signed in</th>
              <th scope="col"><span class="visually-hidden">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="member in members" :key="member.id">
              <td>
                <span class="member-name">{{ member.name }}</span>
                <span v-if="member.id === myUserId" class="badge badge-accent">You</span>
                <span class="subtle small block">{{ member.email }}</span>
              </td>
              <td>
                <select
                  class="select role"
                  :value="member.role"
                  :disabled="!canChange(member)"
                  :aria-label="`Role of ${member.name}`"
                  :title="canChange(member) ? undefined : 'Only an owner changes an owner'"
                  @change="changeRole(member, $event)"
                >
                  <option v-for="r in MEMBER_ROLES" :key="r" :value="r" :disabled="r === 'owner' && !isOwner">{{ r }}</option>
                </select>
              </td>
              <td class="hide-sm subtle small">{{ member.last_login_at ? formatRelative(member.last_login_at) : "Never" }}</td>
              <td class="actions">
                <button
                  v-if="canChange(member)"
                  type="button"
                  class="btn btn-ghost btn-sm"
                  :aria-label="`Remove ${member.name}`"
                  @click="removeMember(member)"
                >
                  Remove
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="invitations.length" class="table-wrap card">
        <table class="table">
          <caption class="caption">Invitations not accepted yet</caption>
          <thead>
            <tr>
              <th scope="col">Email</th>
              <th scope="col">Role</th>
              <th scope="col" class="hide-sm">Invited by</th>
              <th scope="col" class="hide-sm">Link works until</th>
              <th scope="col"><span class="visually-hidden">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="invitation in invitations" :key="invitation.id" :class="{ expired: expired(invitation) }">
              <td>
                {{ invitation.email }}
                <span v-if="expired(invitation)" class="badge">Expired</span>
              </td>
              <td><span class="chip">{{ invitation.role }}</span></td>
              <td class="hide-sm subtle small">{{ invitation.invited_by?.name ?? "An API key" }}</td>
              <td class="hide-sm subtle small">{{ formatDate(invitation.expires_at) }}</td>
              <td class="actions">
                <button type="button" class="btn btn-ghost btn-sm" :aria-label="`Revoke the invitation for ${invitation.email}`" @click="revoke(invitation)">
                  Revoke
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </section>
</template>

<style scoped>
.members {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.invite {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 10px 14px;
  padding: 12px 14px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  color: var(--text-2);
  font-size: 12.5px;
  font-weight: 550;
}

.email {
  flex: 1 1 220px;
}

.created {
  align-items: flex-start;
}

.created-body {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.secret {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.secret code {
  overflow-wrap: anywhere;
  padding: 4px 8px;
  border-radius: var(--radius-sm);
  background: var(--surface);
  user-select: all;
}

.table-wrap {
  overflow-x: auto;
}

.table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13.5px;
}

.caption {
  padding: 10px 12px 0;
  color: var(--text-2);
  font-size: 12.5px;
  font-weight: 600;
  text-align: left;
}

.table th,
.table td {
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
  text-align: left;
  vertical-align: middle;
}

.table th {
  color: var(--text-3);
  font-size: 12px;
  font-weight: 600;
}

.table tbody tr:last-child td {
  border-bottom: 0;
}

.member-name {
  font-weight: 600;
}

.block {
  display: block;
}

.badge {
  margin-left: 6px;
}

.role {
  width: auto;
  min-width: 110px;
}

.expired td {
  opacity: 0.6;
}

.actions {
  text-align: right;
}

.table-skeleton {
  height: 160px;
  border-radius: var(--radius);
}

@media (max-width: 640px) {
  .hide-sm {
    display: none;
  }
}
</style>
