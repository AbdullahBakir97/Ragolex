<script setup lang="ts">
import {
  CircleAlert,
  CircleCheck,
  Clock,
  Eye,
  FileCode,
  FileText,
  FileType2,
  LoaderCircle,
  RefreshCw,
  Settings2,
  Tag,
  Trash2,
} from "@lucide/vue";
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";

import { ApiError, api } from "@/api/client";
import { DEFAULT_PROCESS_OPTIONS, type FileInfo, type ProcessOptions } from "@/api/types";
import ChunkDrawer from "@/components/ChunkDrawer.vue";
import FileDropzone from "@/components/FileDropzone.vue";
import PagerControls from "@/components/PagerControls.vue";
import TagInput from "@/components/TagInput.vue";
import WebsiteSources from "@/components/WebsiteSources.vue";
import { FINISHED, type Stage, useIngest } from "@/composables/useIngest";
import { useProject } from "@/composables/useProject";
import { useProjects } from "@/composables/useProjects";
import { useToasts } from "@/composables/useToasts";
import { fileKind } from "@/lib/fileTypes";
import { formatBytes, formatNumber, formatRelative } from "@/lib/format";

const LIMIT = 20;
const { name, project, refresh: refreshProject, tags: projectTags } = useProject();
const tagSuggestions = computed(() => projectTags.value.map((t) => t.tag));
const { refresh: refreshProjects } = useProjects();
const toasts = useToasts();
const router = useRouter();

const files = ref<FileInfo[]>([]);
const total = ref(0);
const offset = ref(0);
const loading = ref(true);
const chunkCounts = ref<Record<string, number>>({});
const reprocessing = ref<string | null>(null);
const viewing = ref<FileInfo | null>(null);
// Only files with this tag are listed; empty lists them all.
const tagFilter = ref("");
// Tags given to the next uploads.
const uploadTags = ref<string[]>([]);
const uploadTagInput = ref<InstanceType<typeof TagInput> | null>(null);

const showOptions = ref(false);
const options = ref<ProcessOptions>({ ...DEFAULT_PROCESS_OPTIONS });
const optionsProblem = computed(() => {
  const { chunk_size, overlap_size } = options.value;
  if (!Number.isInteger(chunk_size) || chunk_size < 1 || chunk_size > 100_000) return "Chunk size must be 1–100,000.";
  if (!Number.isInteger(overlap_size) || overlap_size < 0) return "Overlap must be 0 or more.";
  if (overlap_size >= chunk_size) return "Overlap must be smaller than the chunk size.";
  return null;
});

// A website sync added or removed pages: show the files as they are now.
async function onSourcesSynced() {
  await Promise.all([load(), refreshProject(), refreshProjects()]);
}

async function load(at = offset.value) {
  try {
    const page = await api.files(name.value, { offset: at, limit: LIMIT }, tagFilter.value || undefined);
    files.value = page.items;
    total.value = page.total;
    offset.value = at;
    void loadChunkCounts(page.items);
  } catch (caught) {
    // A new project has no files, so the server does not know it yet.
    if (!(caught instanceof ApiError && caught.signal === "project_not_found")) {
      toasts.error("Could not load the files", caught instanceof ApiError ? caught.message : undefined);
    }
    files.value = [];
    total.value = 0;
  } finally {
    loading.value = false;
  }
}

async function loadChunkCounts(items: FileInfo[]) {
  const counts = await Promise.all(
    items.map((file) =>
      api
        .chunks(name.value, file.file_id, { limit: 1 })
        .then((page) => [file.file_id, page.total] as const)
        .catch(() => null),
    ),
  );
  chunkCounts.value = { ...chunkCounts.value, ...Object.fromEntries(counts.filter((c) => c !== null)) };
}

let refreshTimer: ReturnType<typeof setTimeout> | undefined;
function onFileReady() {
  // Several files can finish close together: refresh once.
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(() => {
    void load();
    void refreshProject();
    void refreshProjects();
  }, 150);
}

const { jobs, running, add, clearFinished } = useIngest(name, options, onFileReady);

function addFiles(selected: File[]) {
  if (optionsProblem.value) {
    showOptions.value = true;
    toasts.error("Check the chunking options", optionsProblem.value);
    return;
  }
  if (uploadTagInput.value && !uploadTagInput.value.commit()) return;
  add(selected, [...uploadTags.value]);
}

// The file whose tags are being edited, and its tags meanwhile.
const tagging = ref<string | null>(null);
const editedTags = ref<string[]>([]);
// In the table's v-for, so Vue keeps it in an array; one row is edited at a time.
const editTagInput = ref<InstanceType<typeof TagInput>[]>([]);
const savingTags = ref(false);

function editTags(file: FileInfo) {
  tagging.value = file.file_id;
  editedTags.value = [...file.tags];
}

async function saveTags(file: FileInfo) {
  if (editTagInput.value[0] && !editTagInput.value[0].commit()) return;
  savingTags.value = true;
  try {
    const saved = await api.setFileTags(name.value, file.file_id, editedTags.value);
    tagging.value = null;
    // A file that lost the tag shown leaves the list.
    if (tagFilter.value && !saved.tags.includes(tagFilter.value)) await load();
    else files.value = files.value.map((f) => (f.file_id === saved.file_id ? saved : f));
    await refreshProject();
  } catch (caught) {
    toasts.error("The tags could not be saved", caught instanceof ApiError ? caught.message : undefined);
  } finally {
    savingTags.value = false;
  }
}

function filterBy(tag: string) {
  tagFilter.value = tagFilter.value === tag ? "" : tag;
}

async function reprocess(file: FileInfo) {
  if (optionsProblem.value) {
    showOptions.value = true;
    return;
  }
  reprocessing.value = file.file_id;
  try {
    const result = await api.process(name.value, file.file_id, options.value);
    chunkCounts.value = { ...chunkCounts.value, [file.file_id]: result.chunks_count };
    try {
      await api.index(name.value, file.file_id);
      toasts.success("File re-processed", `${formatNumber(result.chunks_count)} chunks, indexed.`);
    } catch (caught) {
      toasts.info("File re-processed, not indexed", caught instanceof ApiError ? caught.message : undefined);
    }
  } catch (caught) {
    toasts.error("Re-processing failed", caught instanceof ApiError ? caught.message : undefined);
  } finally {
    reprocessing.value = null;
    await refreshProject();
  }
}

const stageLabel: Record<Stage, string> = {
  queued: "Waiting",
  uploading: "Uploading",
  waiting: "Waiting for a worker",
  processing: "Splitting into chunks",
  indexing: "Indexing",
  done: "Ready",
  duplicate: "Already in the project",
  "not-indexed": "Not indexed",
  failed: "Failed",
};

const busyStages: Stage[] = ["uploading", "waiting", "processing", "indexing"];
const finished = computed(() => jobs.value.some((job) => FINISHED.includes(job.stage)));

// The file whose deletion waits for confirmation, and the one being deleted.
const confirmingDelete = ref<string | null>(null);
const deleting = ref<string | null>(null);

async function deleteFile(file: FileInfo) {
  deleting.value = file.file_id;
  try {
    await api.deleteFile(name.value, file.file_id);
    toasts.success("File deleted", `${file.original_name} and its chunks are gone.`);
    // The last file of a page: show the page before.
    await load(files.value.length === 1 && offset.value > 0 ? offset.value - LIMIT : offset.value);
    await refreshProject();
  } catch (caught) {
    toasts.error("The file could not be deleted", caught instanceof ApiError ? caught.message : undefined);
  } finally {
    deleting.value = null;
    confirmingDelete.value = null;
  }
}

const projectConfirmation = ref("");
const deletingProject = ref(false);

async function deleteProject() {
  if (projectConfirmation.value !== name.value) return;
  deletingProject.value = true;
  try {
    await api.deleteProject(name.value);
    toasts.success("Project deleted", `${name.value} and everything in it are gone.`);
    await refreshProjects();
    await router.push({ name: "home" });
  } catch (caught) {
    toasts.error("The project could not be deleted", caught instanceof ApiError ? caught.message : undefined);
  } finally {
    deletingProject.value = false;
  }
}
const isEmpty = computed(() => !loading.value && total.value === 0 && jobs.value.length === 0);

const kind = (file: FileInfo) => fileKind(file);

watch(name, () => {
  loading.value = true;
  chunkCounts.value = {};
  tagFilter.value = "";
  uploadTags.value = [];
  void load(0);
});
watch(tagFilter, () => void load(0));
// A filter whose last file lost the tag shows all files again.
watch(projectTags, (tags) => {
  if (tagFilter.value && !tags.some((t) => t.tag === tagFilter.value)) tagFilter.value = "";
});
onMounted(() => load(0));
</script>

<template>
  <section class="documents">
    <div class="toolbar">
      <div>
        <h2>Documents</h2>
        <p class="muted small">Files are split into chunks and indexed as soon as they are uploaded.</p>
      </div>
      <button class="btn btn-sm" :aria-expanded="showOptions" @click="showOptions = !showOptions">
        <Settings2 :size="14" /> Chunking
      </button>
    </div>

    <div v-if="showOptions" class="options card">
      <label class="field">
        <span>Chunk size (characters)</span>
        <input v-model.number="options.chunk_size" class="input" type="number" min="1" max="100000" step="100" />
      </label>
      <label class="field">
        <span>Overlap (characters)</span>
        <input v-model.number="options.overlap_size" class="input" type="number" min="0" step="50" />
      </label>
      <p class="hint small" :class="optionsProblem ? 'error' : 'subtle'">
        {{
          optionsProblem ??
          "Applies to new uploads and to re-processing. Overlap repeats the end of one chunk at the start of the next."
        }}
      </p>
    </div>

    <FileDropzone :large="isEmpty" @files="addFiles" />
    <div class="upload-tags">
      <span class="small muted">Tag new uploads</span>
      <TagInput
        ref="uploadTagInput"
        v-model="uploadTags"
        :suggestions="tagSuggestions"
        label="Tags for new uploads"
        placeholder="Optional, e.g. handbook, release-notes"
      />
    </div>

    <div v-if="jobs.length" class="jobs card">
      <div class="jobs-head">
        <h3>{{ running ? "Processing uploads…" : "Uploads" }}</h3>
        <button v-if="finished && !running" class="btn btn-ghost btn-sm" @click="clearFinished">Clear</button>
      </div>
      <ul class="job-list">
        <li v-for="job in jobs" :key="job.id" class="job">
          <span class="job-icon" :class="job.stage">
            <LoaderCircle v-if="busyStages.includes(job.stage)" :size="16" class="spin" />
            <CircleCheck v-else-if="job.stage === 'done' || job.stage === 'duplicate'" :size="16" />
            <CircleAlert v-else-if="job.stage === 'failed' || job.stage === 'not-indexed'" :size="16" />
            <Clock v-else :size="16" />
          </span>
          <div class="job-body">
            <div class="job-line">
              <span class="job-name">{{ job.name }}</span>
              <span class="subtle small">{{ formatBytes(job.size) }}</span>
            </div>
            <div v-if="job.stage === 'uploading' || job.stage === 'indexing'" class="progress" role="progressbar" :aria-valuenow="Math.round(job.progress * 100)" aria-valuemin="0" aria-valuemax="100">
              <span :style="{ width: `${job.progress * 100}%` }" />
            </div>
            <p class="small" :class="job.error ? 'job-error' : 'subtle'">
              {{ job.error ?? stageLabel[job.stage] }}
              <template v-if="job.stage === 'done' && job.chunks !== null">· {{ formatNumber(job.chunks) }} chunks</template>
            </p>
          </div>
          <span class="badge" :class="{
            'badge-success': job.stage === 'done' || job.stage === 'duplicate',
            'badge-danger': job.stage === 'failed',
            'badge-warning': job.stage === 'not-indexed',
            'badge-accent': busyStages.includes(job.stage),
          }">{{ stageLabel[job.stage] }}</span>
        </li>
      </ul>
    </div>

    <div v-if="projectTags.length" class="tag-filter" role="group" aria-label="Show documents tagged">
      <Tag :size="14" class="subtle" aria-hidden="true" />
      <button type="button" class="badge filter" :class="{ on: !tagFilter }" :aria-pressed="!tagFilter" @click="tagFilter = ''">
        All
      </button>
      <button
        v-for="t in projectTags"
        :key="t.tag"
        type="button"
        class="badge filter"
        :class="{ on: tagFilter === t.tag }"
        :aria-pressed="tagFilter === t.tag"
        @click="filterBy(t.tag)"
      >
        {{ t.tag }} <span class="count">{{ formatNumber(t.files) }}</span>
      </button>
    </div>

    <div v-if="loading" class="card table-card">
      <div v-for="i in 3" :key="i" class="skeleton row-skeleton" />
    </div>

    <div v-else-if="total > 0" class="card table-card">
      <table class="table">
        <thead>
          <tr>
            <th>Name</th>
            <th class="hide-sm">Size</th>
            <th class="num">Chunks</th>
            <th class="hide-sm">Uploaded</th>
            <th class="actions-col"><span class="visually-hidden">Actions</span></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="file in files" :key="file.file_id">
            <td>
              <div class="file-name">
                <span class="file-icon" :class="kind(file).toLowerCase()" :title="kind(file)">
                  <FileType2 v-if="kind(file) === 'PDF' || kind(file) === 'Word'" :size="16" />
                  <FileCode v-else-if="kind(file) === 'Markdown' || kind(file) === 'HTML'" :size="16" />
                  <FileText v-else :size="16" />
                </span>
                <div class="file-text">
                  <button class="link-button" @click="viewing = file">{{ file.original_name }}</button>
                  <span class="subtle small mono file-id" :title="file.file_id">{{ file.file_id }}</span>
                  <form v-if="tagging === file.file_id" class="tag-editor" @submit.prevent="saveTags(file)">
                    <TagInput
                      ref="editTagInput"
                      v-model="editedTags"
                      :suggestions="tagSuggestions"
                      :label="`Tags of ${file.original_name}`"
                      placeholder="No tags"
                    />
                    <button class="btn btn-primary btn-sm" type="submit" :disabled="savingTags">
                      <LoaderCircle v-if="savingTags" :size="14" class="spin" />
                      Save
                    </button>
                    <button class="btn btn-ghost btn-sm" type="button" @click="tagging = null">Cancel</button>
                  </form>
                  <span v-else-if="file.tags.length" class="file-tags">
                    <button
                      v-for="tag in file.tags"
                      :key="tag"
                      type="button"
                      class="chip"
                      :title="`Show only documents tagged ${tag}`"
                      @click="filterBy(tag)"
                    >
                      {{ tag }}
                    </button>
                  </span>
                </div>
              </div>
            </td>
            <td class="hide-sm muted">{{ formatBytes(file.size_bytes) }}</td>
            <td class="num">
              <span v-if="chunkCounts[file.file_id] === undefined" class="skeleton count-skeleton" />
              <span v-else-if="chunkCounts[file.file_id] === 0" class="badge badge-warning">None</span>
              <span v-else>{{ formatNumber(chunkCounts[file.file_id]!) }}</span>
            </td>
            <td class="hide-sm muted" :title="file.created_at">{{ formatRelative(file.created_at) }}</td>
            <td v-if="confirmingDelete === file.file_id" class="actions-col confirm-col">
              <span class="small">Delete with its chunks?</span>
              <button class="btn btn-danger btn-sm" :disabled="deleting !== null" @click="deleteFile(file)">
                <LoaderCircle v-if="deleting === file.file_id" :size="14" class="spin" />
                Delete
              </button>
              <button class="btn btn-ghost btn-sm" @click="confirmingDelete = null">Cancel</button>
            </td>
            <td v-else class="actions-col">
              <button class="btn btn-ghost btn-sm btn-icon" title="View chunks" aria-label="View chunks" @click="viewing = file">
                <Eye :size="15" />
              </button>
              <button
                class="btn btn-ghost btn-sm btn-icon"
                title="Edit tags"
                :aria-label="`Edit the tags of ${file.original_name}`"
                @click="editTags(file)"
              >
                <Tag :size="15" />
              </button>
              <button
                class="btn btn-ghost btn-sm btn-icon"
                title="Re-process with the current chunking options"
                aria-label="Re-process"
                :disabled="reprocessing !== null"
                @click="reprocess(file)"
              >
                <LoaderCircle v-if="reprocessing === file.file_id" :size="15" class="spin" />
                <RefreshCw v-else :size="15" />
              </button>
              <button
                class="btn btn-ghost btn-sm btn-icon"
                :title="`Delete ${file.original_name}`"
                :aria-label="`Delete ${file.original_name}`"
                @click="confirmingDelete = file.file_id"
              >
                <Trash2 :size="15" />
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      <div class="table-foot">
        <PagerControls :total="total" :offset="offset" :limit="LIMIT" noun="files" @change="load" />
      </div>
    </div>

    <p v-else-if="!jobs.length && project === null" class="subtle small center">
      Upload a document to start. The project is saved with its first file.
    </p>

    <WebsiteSources :project="name" :tag-suggestions="tagSuggestions" @synced="onSourcesSynced" />

    <section v-if="project" class="danger card" aria-labelledby="delete-project">
      <div>
        <h3 id="delete-project">Delete this project</h3>
        <p class="muted small">
          Deletes {{ formatNumber(project.files_count) }} files with their chunks, answers, conversations and ratings.
          This cannot be undone.
        </p>
      </div>
      <form class="danger-form" @submit.prevent="deleteProject">
        <input
          v-model="projectConfirmation"
          class="input"
          :placeholder="`Type ${name} to confirm`"
          :aria-label="`Type ${name} to confirm`"
          autocomplete="off"
        />
        <button class="btn btn-danger" type="submit" :disabled="projectConfirmation !== name || deletingProject">
          <LoaderCircle v-if="deletingProject" :size="14" class="spin" />
          Delete project
        </button>
      </form>
    </section>

    <ChunkDrawer :project="name" :file="viewing" @close="viewing = null" />
  </section>
</template>

<style scoped>
.confirm-col {
  white-space: nowrap;
}

.upload-tags {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: -4px;
}

.upload-tags .tag-input {
  flex: 1;
}

@media (max-width: 560px) {
  .upload-tags {
    flex-direction: column;
    align-items: stretch;
    gap: 4px;
  }
}

.tag-filter {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.filter {
  border: 1px solid transparent;
  font: inherit;
  font-size: 12px;
  font-weight: 550;
  cursor: pointer;
}

.filter.on {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent-text);
}

.filter .count {
  opacity: 0.7;
}

.file-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 4px;
}

.file-tags .chip {
  border: 0;
  font: inherit;
  font-size: 12px;
  font-weight: 550;
  cursor: pointer;
}

.tag-editor {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 6px;
  margin-top: 6px;
}

.tag-editor .tag-input {
  flex: 1 1 220px;
}

.confirm-col .small {
  margin-right: 6px;
}

.danger {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px 24px;
  margin-top: 18px;
  padding: 16px 18px;
  border-color: color-mix(in srgb, var(--danger) 35%, var(--border));
}

.danger h3 {
  color: var(--danger);
}

.danger-form {
  display: flex;
  gap: 8px;
}

.danger-form .input {
  width: 220px;
}

.documents {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.toolbar {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
}

.options {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 220px)) 1fr;
  align-items: end;
  gap: 14px;
  padding: 14px 16px;
}

@media (max-width: 720px) {
  .options {
    grid-template-columns: 1fr 1fr;
  }

  .options .hint {
    grid-column: 1 / -1;
  }
}

.hint {
  align-self: center;
}

.error,
.job-error {
  color: var(--danger);
}

.jobs {
  padding: 12px 14px;
}

.jobs-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}

.job-list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.job {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 0;
  border-top: 1px solid var(--border);
}

.job:first-child {
  border-top: 0;
}

.job-icon {
  display: grid;
  flex: none;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: var(--surface-2);
  color: var(--text-3);
}

.job-icon.done {
  background: var(--success-soft);
  color: var(--success);
}

.job-icon.failed {
  background: var(--danger-soft);
  color: var(--danger);
}

.job-icon.not-indexed {
  background: var(--warning-soft);
  color: var(--warning);
}

.job-icon.uploading,
.job-icon.processing,
.job-icon.indexing {
  background: var(--accent-soft);
  color: var(--accent);
}

.job-body {
  flex: 1;
  min-width: 0;
}

.job-line {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.job-name {
  overflow: hidden;
  font-weight: 550;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.progress {
  height: 4px;
  margin: 6px 0 4px;
  border-radius: 2px;
  background: var(--surface-3);
  overflow: hidden;
}

.progress span {
  display: block;
  height: 100%;
  background: var(--accent);
  transition: width 0.2s;
}

@media (max-width: 560px) {
  .job > .badge {
    display: none;
  }
}

.table-card {
  overflow: hidden;
}

.table {
  width: 100%;
  border-collapse: collapse;
}

.table th {
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--text-3);
  font-size: 12px;
  font-weight: 600;
  text-align: left;
  letter-spacing: 0.02em;
}

.table td {
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  vertical-align: middle;
}

.table tbody tr:last-child td {
  border-bottom: 0;
}

.table tbody tr:hover {
  background: var(--surface-2);
}

.num {
  text-align: right !important;
  font-variant-numeric: tabular-nums;
}

.actions-col {
  width: 1%;
  white-space: nowrap;
  text-align: right;
}

@media (max-width: 640px) {
  .hide-sm {
    display: none;
  }
}

.file-name {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.file-icon {
  display: grid;
  flex: none;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: var(--surface-2);
  color: var(--text-2);
}

.file-icon.pdf {
  background: var(--danger-soft);
  color: var(--danger);
}

.file-icon.word {
  background: var(--accent-soft);
  color: var(--accent-text);
}

.file-icon.markdown,
.file-icon.html {
  background: var(--warning-soft);
  color: var(--warning);
}

.file-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.link-button {
  padding: 0;
  border: 0;
  background: none;
  color: var(--text);
  font: inherit;
  font-weight: 550;
  text-align: left;
  overflow-wrap: anywhere;
  cursor: pointer;
}

.link-button:hover {
  color: var(--accent);
}

.file-id {
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Long ids (a source's pages are named after their address) stay within a phone's width. */
@media (max-width: 560px) {
  .file-id {
    max-width: 150px;
  }
}

.count-skeleton {
  display: inline-block;
  width: 32px;
  height: 14px;
}

.row-skeleton {
  height: 44px;
  margin: 8px;
}

.table-foot {
  padding: 0 14px;
}

.table-foot:has(.pager) {
  padding: 10px 14px;
  border-top: 1px solid var(--border);
}

.center {
  text-align: center;
}
</style>
