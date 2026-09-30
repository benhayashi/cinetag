// CineTag - Frontend Controller

let scannedVideos = [];
let renamePreviews = [];
let pollInterval = null;

document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  initIntakeModes();
  initDropzone();
  initModeADropzone();
  initQuickAutoRenameToggle();
  initSettings();
  initScanner();
  initQueueControls();
  initRenaming();
  initPrivacy();
  initResultsModal();
  initFacesTab();
  initFsBrowser();
  initConflictModal();
  
  // Initial config load & backend status
  loadConfig();
  checkFFmpegStatus();
  pollStatus();
  pollInterval = setInterval(pollStatus, 1500);
});



// --- Tab Navigation ---
function initTabs() {
  const savedTab = localStorage.getItem("active_tab") || "tab-processor";

  document.querySelectorAll(".nav-tab").forEach(tab => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".nav-tab").forEach(t => t.classList.remove("active"));
      document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));
      
      tab.classList.add("active");
      const targetId = tab.dataset.tab;
      localStorage.setItem("active_tab", targetId);
      document.getElementById(targetId).classList.add("active");

      if (targetId === "tab-privacy") {
        refreshStorageInfo();
      } else if (targetId === "tab-connectors") {
        loadConfig();
      } else if (targetId === "tab-faces") {
        loadFaces();
      }
    });
  });

  // Restore saved tab if exists
  const targetTabBtn = document.querySelector(`.nav-tab[data-tab="${savedTab}"]`);
  if (targetTabBtn && savedTab !== "tab-processor") {
    targetTabBtn.click();
  }

  // Header Brand Logo/Title returns to Batch Processor
  const brandHome = document.getElementById("header-brand-home");
  if (brandHome) {
    brandHome.addEventListener("click", () => {
      const procTab = document.querySelector('.nav-tab[data-tab="tab-processor"]');
      if (procTab) procTab.click();
    });
  }

  // Warning banner configure button opens Settings
  const btnBannerLocate = document.getElementById("btn-banner-locate-ffmpeg");
  if (btnBannerLocate) {
    btnBannerLocate.addEventListener("click", () => {
      const connTab = document.querySelector('.nav-tab[data-tab="tab-connectors"]');
      if (connTab) {
        connTab.click();
        const card = document.getElementById("card-ffmpeg-management");
        if (card) card.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
  }
}

// --- Intake Mode Switcher ---
function initIntakeModes() {
  const btnLocal = document.getElementById("mode-btn-local");
  const btnUpload = document.getElementById("mode-btn-upload");
  const secLocal = document.getElementById("section-mode-local");
  const secUpload = document.getElementById("section-mode-upload");

  function setMode(mode) {
    localStorage.setItem("intake_mode", mode);
    if (mode === "upload") {
      btnUpload.classList.add("active");
      btnLocal.classList.remove("active");
      secUpload.classList.remove("hidden");
      secLocal.classList.add("hidden");
      pollUploads();
    } else {
      btnLocal.classList.add("active");
      btnUpload.classList.remove("active");
      secLocal.classList.remove("hidden");
      secUpload.classList.add("hidden");
    }
  }

  btnLocal.addEventListener("click", () => setMode("local"));
  btnUpload.addEventListener("click", () => setMode("upload"));

  // Restore saved intake mode
  const savedMode = localStorage.getItem("intake_mode") || "local";
  if (savedMode === "upload") {
    setMode("upload");
  }
}

// --- Drag & Drop Dropzone Controller ---
function initDropzone() {
  const dropzone = document.getElementById("dropzone");
  const filePicker = document.getElementById("file-picker");
  const browseLink = document.querySelector(".browse-link");
  const btnClearAll = document.getElementById("btn-clear-all-uploads");

  if (!dropzone) return;

  // Open file dialog on click
  dropzone.addEventListener("click", (e) => {
    if (e.target.tagName !== "BUTTON" && !e.target.closest("button")) {
      filePicker.click();
    }
  });

  if (browseLink) {
    browseLink.addEventListener("click", (e) => {
      e.stopPropagation();
      filePicker.click();
    });
  }

  filePicker.addEventListener("change", () => {
    if (filePicker.files && filePicker.files.length > 0) {
      handleFiles(Array.from(filePicker.files));
      filePicker.value = "";
    }
  });

  // Drag over / leave / drop
  ["dragenter", "dragover"].forEach(name => {
    dropzone.addEventListener(name, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropzone.classList.add("dragover");
    });
  });

  ["dragleave", "dragend"].forEach(name => {
    dropzone.addEventListener(name, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropzone.classList.remove("dragover");
    });
  });

  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropzone.classList.remove("dragover");
    if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFiles(Array.from(e.dataTransfer.files));
    }
  });

  if (btnClearAll) {
    btnClearAll.addEventListener("click", async () => {
      if (confirm("Delete all uploaded videos and their generated sidecars from the server?")) {
        try {
          const res = await fetch("/api/storage/clear-uploads", { method: "POST" });
          const data = await res.json();
          alert(`Cleared uploaded videos! Freed ${data.freed_formatted}.`);
          pollUploads();
        } catch (e) {
          alert("Error clearing uploads: " + e.message);
        }
      }
    });
  }
}

// --- Mode A In-Place Local Drag & Drop ---
function initModeADropzone() {
  const dropzone = document.getElementById("mode-a-dropzone");
  const statusEl = document.getElementById("mode-a-drop-status");
  if (!dropzone) return;

  // Click dropzone to open native folder dialog
  dropzone.addEventListener("click", (e) => {
    if (e.target.tagName !== "BUTTON" && !e.target.closest("button") && !e.target.closest("a")) {
      const btnBrowse = document.getElementById("btn-browse-folder");
      if (btnBrowse && !btnBrowse.disabled) btnBrowse.click();
    }
  });

  ["dragenter", "dragover"].forEach(name => {
    dropzone.addEventListener(name, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropzone.classList.add("dragover");
    });
  });

  ["dragleave", "dragend"].forEach(name => {
    dropzone.addEventListener(name, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropzone.classList.remove("dragover");
    });
  });

  dropzone.addEventListener("drop", async (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropzone.classList.remove("dragover");

    if (statusEl) {
      statusEl.textContent = "🔍 Resolving local files...";
      statusEl.style.color = "#60a5fa";
      statusEl.classList.remove("hidden");
    }

    const rawUriList = e.dataTransfer.getData("text/uri-list") || "";
    const rawPlain = e.dataTransfer.getData("text/plain") || "";
    const uris = [];
    (rawUriList + "\n" + rawPlain).split(/[\r\n]+/).forEach(line => {
      const trimmed = line.trim();
      if (trimmed && (trimmed.startsWith("file://") || trimmed.startsWith("/"))) {
        uris.push(trimmed);
      }
    });

    const filenames = [];
    const filesMeta = [];

    // Helper to traverse dropped folders if supported by the browser
    async function readEntry(entry) {
      if (!entry) return;
      if (entry.isFile) {
        if (!filenames.includes(entry.name)) filenames.push(entry.name);
      } else if (entry.isDirectory) {
        if (!filenames.includes(entry.name)) filenames.push(entry.name);
        try {
          const reader = entry.createReader();
          const readBatch = () => new Promise((resolve) => {
            reader.readEntries((entries) => resolve(entries || []), () => resolve([]));
          });
          let batch;
          do {
            batch = await readBatch();
            for (const sub of batch) {
              await readEntry(sub);
            }
          } while (batch && batch.length > 0);
        } catch (err) {
          console.warn("Folder reader error:", err);
        }
      }
    }

    if (e.dataTransfer.items && e.dataTransfer.items.length > 0) {
      for (const item of e.dataTransfer.items) {
        if (item.kind === "file") {
          const entry = item.webkitGetAsEntry ? item.webkitGetAsEntry() : null;
          if (entry) {
            await readEntry(entry);
          }
          const f = item.getAsFile ? item.getAsFile() : null;
          if (f) {
            if (f.name && !filenames.includes(f.name)) filenames.push(f.name);
            filesMeta.push({ name: f.name, size: f.size });
            if (f.path && typeof f.path === "string") uris.push(f.path);
          }
        }
      }
    } else if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      for (const f of e.dataTransfer.files) {
        if (f.name) {
          filenames.push(f.name);
          filesMeta.push({ name: f.name, size: f.size });
        }
        if (f.path && typeof f.path === "string") {
          uris.push(f.path);
        }
      }
    }

    const currentFolder = document.getElementById("scan-folder-path")?.value.trim() || null;

    if (uris.length === 0 && filenames.length === 0) {
      if (statusEl) {
        statusEl.textContent = "⚠️ No local files detected in drop event.";
        statusEl.style.color = "#f87171";
        statusEl.classList.remove("hidden");
        setTimeout(() => statusEl.classList.add("hidden"), 4000);
      }
      return;
    }

    try {
      const res = await fetch("/api/files/resolve-local", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          uris: Array.from(new Set(uris)),
          filenames: Array.from(new Set(filenames)),
          files_meta: filesMeta,
          current_folder: currentFolder
        })
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Server failed to resolve files");
      }

      const data = await res.json();
      const resolvedPaths = data.resolved_paths || [];

      if (data.detected_folder) {
        const folderInput = document.getElementById("scan-folder-path");
        if (folderInput) {
          folderInput.value = data.detected_folder;
        }
      }

      if (resolvedPaths.length === 0) {
        if (statusEl) {
          statusEl.textContent = "⚠️ No matching local video files found on disk. Click 'Browse Folder' or 'Select Files'.";
          statusEl.style.color = "#f87171";
          setTimeout(() => statusEl.classList.add("hidden"), 5000);
        }
        return;
      }

      if (statusEl) {
        statusEl.innerHTML = `✅ Adding <b>${resolvedPaths.length}</b> local video(s) to queue...`;
        statusEl.style.color = "#34d399";
      }

      // Automatically queue resolved local files for in-place processing
      await requestEnqueueWithConflictCheck(resolvedPaths, false);

      if (statusEl) {
        statusEl.innerHTML = `✅ Queued <b>${resolvedPaths.length}</b> local video(s) for in-place processing!`;
        statusEl.style.color = "#34d399";
        setTimeout(() => statusEl.classList.add("hidden"), 5000);
      }
    } catch (err) {
      if (statusEl) {
        statusEl.textContent = `❌ Error: ${err.message}`;
        statusEl.style.color = "#f87171";
        setTimeout(() => statusEl.classList.add("hidden"), 5000);
      }
    }
  });
}

// --- Quick Auto-Rename Toggle in Header ---
function initQuickAutoRenameToggle() {
  const toggle = document.getElementById("quick-auto-rename-toggle");
  const label = document.getElementById("quick-auto-rename-label");
  if (!toggle) return;

  toggle.addEventListener("change", async (e) => {
    const isChecked = e.target.checked;
    if (label) {
      label.textContent = isChecked ? "ON" : "OFF";
      label.style.color = isChecked ? "#34d399" : "#94a3b8";
    }
    const settingsChk = document.getElementById("cfg-auto-rename");
    if (settingsChk) settingsChk.checked = isChecked;

    try {
      await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ auto_rename: isChecked })
      });
    } catch (err) {
      console.error("Failed to update auto_rename toggle:", err);
    }
  });
}

async function handleFiles(files) {
  for (const file of files) {
    await uploadSingleFile(file);
  }
  pollUploads();
}

function uploadSingleFile(file) {
  return new Promise((resolve) => {
    const progressBox = document.getElementById("upload-progress-box");
    const nameEl = document.getElementById("upload-filename");
    const pctEl = document.getElementById("upload-percent");
    const barEl = document.getElementById("upload-bar-fill");

    progressBox.classList.remove("hidden");
    nameEl.textContent = `Uploading ${file.name}...`;
    pctEl.textContent = "0%";
    barEl.style.width = "0%";

    const formData = new FormData();
    formData.append("file", file);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/upload", true);

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) {
        const pct = Math.round((e.loaded / e.total) * 100);
        pctEl.textContent = `${pct}%`;
        barEl.style.width = `${pct}%`;
      }
    };

    xhr.onload = () => {
      progressBox.classList.add("hidden");
      if (xhr.status === 200) {
        console.log("Uploaded successfully:", file.name);
      } else {
        alert(`Failed to upload ${file.name}: ${xhr.statusText}`);
      }
      resolve();
    };

    xhr.onerror = () => {
      progressBox.classList.add("hidden");
      alert(`Network error uploading ${file.name}`);
      resolve();
    };

    xhr.send(formData);
  });
}

async function pollUploads() {
  const tbody = document.getElementById("uploads-tbody");
  if (!tbody) return;

  try {
    const res = await fetch("/api/uploads");
    if (!res.ok) return;
    const data = await res.json();
    const uploads = data.uploads || [];

    if (uploads.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" class="empty-state">No uploaded videos in staging yet. Drag files into the box above to start.</td></tr>`;
      return;
    }

    tbody.innerHTML = uploads.map(item => {
      const statusClass = item.status === "completed" ? "processed" : (item.status === "failed" ? "danger" : "unprocessed");
      const sidecars = item.sidecars || {};
      const isCompleted = item.status === "completed" || sidecars.txt || sidecars.json;

      const downloadPills = [];
      if (sidecars.nfo) {
        downloadPills.push(`<a class="btn-download-pill" href="/api/download?file_path=${encodeURIComponent(sidecars.nfo)}" download title="Download Kodi / Jellyfin / Plex NFO">🎬 .NFO</a>`);
      }
      if (sidecars.xmp) {
        downloadPills.push(`<a class="btn-download-pill" href="/api/download?file_path=${encodeURIComponent(sidecars.xmp)}" download title="Download XMP / XML Sidecar">🏷️ .XMP</a>`);
      }
      if (sidecars.txt) {
        downloadPills.push(`<a class="btn-download-pill" href="/api/download?file_path=${encodeURIComponent(sidecars.txt)}" download title="Download Text Description">📄 .TXT</a>`);
      }
      if (sidecars.json) {
        downloadPills.push(`<a class="btn-download-pill" href="/api/download?file_path=${encodeURIComponent(sidecars.json)}" download title="Download Full JSON Metadata">📦 .JSON</a>`);
      }
      if (sidecars.srt) {
        downloadPills.push(`<a class="btn-download-pill" href="/api/download?file_path=${encodeURIComponent(sidecars.srt)}" download title="Download SRT Subtitles">💬 .SRT</a>`);
      } else if (isCompleted) {
        downloadPills.push(`<a class="btn-download-pill" href="/api/download/srt?file_path=${encodeURIComponent(item.path)}" download title="Download Generated SRT Subtitles">💬 .SRT</a>`);
      }
      if (sidecars.edl) {
        downloadPills.push(`<a class="btn-download-pill" href="/api/download?file_path=${encodeURIComponent(sidecars.edl)}" download title="Download EDL Timeline Markers">🎞️ .EDL</a>`);
      }

      const downloadsHtml = downloadPills.length > 0 
        ? `<div class="download-pill-group">${downloadPills.join("")}</div>` 
        : `<span class="text-muted"><small>${item.status === 'failed' ? 'Failed' : 'Generating...'}</small></span>`;

      const viewResultsHtml = isCompleted
        ? `<button class="btn-view-results" onclick="openResultsModal('${escapeHtml(item.path)}')">👁️ View Results</button>`
        : '';

      const srtBadge = item.has_srt 
        ? `<span class="badge-tag" style="background:#1e3a5f; color:#93c5fd; font-size:0.7rem; margin-left:6px;" title="Accompanying subtitle: ${escapeHtml(item.srt_filename || '')}">💬 .SRT paired</span>`
        : '';

      return `
        <tr>
          <td>
            <b>${escapeHtml(item.filename)}</b>${srtBadge}
            <div class="text-muted" style="font-size:0.75rem; margin-top:4px; display:flex; gap:0.4rem; align-items:center; flex-wrap:wrap;">
              <button class="btn btn-sm btn-primary" onclick="openDownloadModal('${escapeHtml(item.path)}', '${escapeHtml(item.filename)}')" style="padding:0.25rem 0.5rem; font-size:0.75rem; min-height:auto;">📥 Download Options...</button>
              <a href="/api/download?file_path=${encodeURIComponent(item.path)}" download style="color:#60a5fa; font-size:0.75rem;">Raw File</a>
            </div>
          </td>
          <td>${item.size_formatted}</td>
          <td>
            <span class="badge-tag ${statusClass}">${escapeHtml(item.stage || item.status)}</span>
            ${viewResultsHtml ? `<div style="margin-top:6px;">${viewResultsHtml}</div>` : ''}
          </td>
          <td>${downloadsHtml}</td>
          <td>
            <button class="btn-delete-action" onclick="deleteUploadedFile('${escapeHtml(item.filename)}')" title="Delete video & sidecars">🗑️</button>
          </td>
        </tr>
      `;
    }).join("");
  } catch (err) {
    console.error("Error polling uploads:", err);
  }
}

async function deleteUploadedFile(filename) {
  if (!confirm(`Delete ${filename} and its generated sidecars from server?`)) return;
  try {
    const res = await fetch(`/api/uploads/${encodeURIComponent(filename)}`, { method: "DELETE" });
    if (res.ok) {
      pollUploads();
    } else {
      const err = await res.json();
      alert(`Delete failed: ${err.detail || "Unknown error"}`);
    }
  } catch (e) {
    alert("Error deleting file: " + e.message);
  }
}


// --- Status Polling ---
async function pollStatus() {
  try {
    const res = await fetch("/api/status");
    if (!res.ok) return;
    const data = await res.json();
    
    // Update stats pills
    document.getElementById("stat-queued").textContent = data.counts.queued;
    document.getElementById("stat-processing").textContent = data.counts.processing;
    document.getElementById("stat-completed").textContent = data.counts.completed;
    document.getElementById("stat-failed").textContent = data.counts.failed;

    // Update active task
    const cur = data.current_task;
    const taskNameEl = document.getElementById("current-task-name");
    const taskStageEl = document.getElementById("current-task-stage");
    const barEl = document.getElementById("progress-bar-fill");
    const subtextEl = document.getElementById("queue-subtext");

    if (cur) {
      taskNameEl.textContent = cur.filename;
      taskStageEl.textContent = `${cur.stage} (${cur.progress}%)`;
      barEl.style.width = `${cur.progress}%`;
      subtextEl.textContent = data.is_paused ? "Paused" : "Processing batch...";
    } else {
      taskNameEl.textContent = data.counts.queued > 0 ? "Waiting to start..." : "Queue is empty";
      taskStageEl.textContent = data.counts.queued > 0 ? "Ready" : "Idle";
      barEl.style.width = data.counts.queued > 0 ? "0%" : (data.counts.completed > 0 ? "100%" : "0%");
      subtextEl.textContent = data.is_paused ? "Paused" : "Idle";
    }

    // Render logs
    renderLogs(data.recent_logs || []);

    // Mode A: Update scanned videos status dynamically and render latest completed result
    if (data.tasks && data.tasks.length > 0) {
      let tableNeedsUpdate = false;
      const completedTasks = data.tasks.filter(t => t.status === "completed");

      completedTasks.forEach(ct => {
        const targetPath = (ct.result && ct.result.final_file_path) || ct.file_path;
        const found = scannedVideos.find(v => v.path === ct.file_path || v.path === targetPath);
        if (found) {
          if (!found.has_sidecar) {
            found.has_sidecar = true;
            tableNeedsUpdate = true;
          }
          found.result = ct.result;
        }
      });

      if (tableNeedsUpdate) {
        renderScannedTable();
      }

      if (completedTasks.length > 0) {
        const latestTask = completedTasks[completedTasks.length - 1];
        renderLatestResult(latestTask);
      }
    }

    // If Mode B (uploads) is currently visible, poll uploads to show progress/results live
    const secUpload = document.getElementById("section-mode-upload");
    if (secUpload && !secUpload.classList.contains("hidden")) {
      pollUploads();
    }

  } catch (err) {
    console.error("Status poll failed:", err);
  }
}

function renderLatestResult(task) {
  const card = document.getElementById("section-latest-result");
  if (!card || !task || !task.result) return;

  const res = task.result;
  const titleEl = document.getElementById("latest-result-title");
  if (titleEl) titleEl.textContent = res.title || "Analysis Complete";

  const fnEl = document.getElementById("latest-result-filename");
  if (fnEl) {
    let fnDisplay = task.filename;
    if (res.suggested_filename && res.suggested_filename !== task.filename) {
      fnDisplay += ` ➔ ${res.suggested_filename}`;
    }
    fnEl.textContent = fnDisplay;
  }

  const sumEl = document.getElementById("latest-result-summary");
  if (sumEl) sumEl.textContent = res.summary || "Video analysis finished successfully.";

  // Tags, People, Animals & Objects
  const tagsEl = document.getElementById("latest-result-tags");
  if (tagsEl) {
    let pills = [];
    if (res.people && res.people.length > 0) {
      res.people.forEach(p => pills.push(`<span class="tag-pill" style="background:#1e3a5f; color:#93c5fd;">👤 ${escapeHtml(p)}</span>`));
    }
    if (res.animals_or_pets && res.animals_or_pets.length > 0) {
      res.animals_or_pets.forEach(a => pills.push(`<span class="tag-pill" style="background:#14532d; color:#86efac;">🐕 ${escapeHtml(a)}</span>`));
    }
    if (res.objects && res.objects.length > 0) {
      res.objects.forEach(o => pills.push(`<span class="tag-pill" style="background:#312e81; color:#c7d2fe;">🎾 ${escapeHtml(o)}</span>`));
    }
    if (res.tags && res.tags.length > 0) {
      res.tags.forEach(t => {
        const isDupe = (res.animals_or_pets && res.animals_or_pets.some(a => a.toLowerCase() === t.toLowerCase())) ||
                       (res.objects && res.objects.some(o => o.toLowerCase() === t.toLowerCase()));
        if (!isDupe) {
          pills.push(`<span class="tag-pill">${escapeHtml(t)}</span>`);
        }
      });
    }

    if (pills.length > 0) {
      const topPills = pills.slice(0, 14);
      let html = topPills.join("");
      if (pills.length > 14) {
        html += `<span class="text-muted" style="font-size:0.75rem; align-self:center;">+${pills.length - 14} more</span>`;
      }
      tagsEl.innerHTML = html;
    } else {
      tagsEl.innerHTML = "";
    }
  }

  // Sidecar downloads
  const dlEl = document.getElementById("latest-result-downloads");
  if (dlEl) {
    const sidecars = res.sidecars || [];
    let dlHtml = "";
    sidecars.forEach(sp => {
      const pLower = sp.toLowerCase();
      let label = "File";
      let icon = "📄";
      if (pLower.endsWith(".txt")) { label = ".TXT"; icon = "📄"; }
      else if (pLower.endsWith(".json")) { label = ".JSON"; icon = "📋"; }
      else if (pLower.endsWith(".nfo")) { label = ".NFO"; icon = "🎬"; }
      else if (pLower.endsWith(".xmp")) { label = ".XMP"; icon = "🏷️"; }
      else if (pLower.endsWith(".edl")) { label = ".EDL"; icon = "✂️"; }
      else if (pLower.endsWith(".srt")) { label = ".SRT"; icon = "💬"; }

      dlHtml += `<a class="btn btn-sm btn-secondary" style="padding:0.25rem 0.5rem; font-size:0.75rem; text-decoration:none;" href="/api/download?file_path=${encodeURIComponent(sp)}" download>${icon} ${label}</a>`;
    });

    // If no .srt sidecar exists on disk but speech transcript is available, offer dynamic .SRT download
    const hasSrtSidecar = sidecars.some(sp => sp.toLowerCase().endsWith(".srt"));
    if (!hasSrtSidecar && (res.audio_transcript || res.subtitles_used)) {
      const targetPath = res.final_file_path || task.file_path;
      dlHtml += `<a class="btn btn-sm btn-secondary" style="padding:0.25rem 0.5rem; font-size:0.75rem; text-decoration:none;" href="/api/download/srt?file_path=${encodeURIComponent(targetPath)}" download title="Download Generated SRT Subtitles">💬 .SRT</a>`;
    }

    dlEl.innerHTML = dlHtml;
  }

  // Button to open full modal
  const btnModal = document.getElementById("btn-open-latest-modal");
  if (btnModal) {
    const targetPath = res.final_file_path || task.file_path;
    btnModal.onclick = () => openResultsModal(targetPath);
  }

  card.classList.remove("hidden");
}

function renderLogs(logs) {
  const terminal = document.getElementById("terminal-logs");
  if (!terminal) return;
  
  // Auto-scroll only if already near bottom
  const isNearBottom = terminal.scrollHeight - terminal.scrollTop - terminal.clientHeight < 50;

  terminal.innerHTML = logs.map(l => {
    return `<div class="log-line ${l.level}">[${l.timestamp}] ${escapeHtml(l.message)}</div>`;
  }).join("");

  if (isNearBottom) {
    terminal.scrollTop = terminal.scrollHeight;
  }
}

// --- Folder Scanner ---
function initScanner() {
  const btnScan = document.getElementById("btn-scan");
  const folderInput = document.getElementById("scan-folder-path");
  const chkRecursive = document.getElementById("scan-recursive");
  const chkHideProcessed = document.getElementById("scan-hide-processed");
  const masterCheck = document.getElementById("master-select");

  btnScan.addEventListener("click", async () => {
    const path = folderInput.value.trim();
    if (!path) {
      alert("Please enter a directory path.");
      return;
    }

    btnScan.disabled = true;
    btnScan.textContent = "Scanning...";

    try {
      const res = await fetch("/api/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          folder_path: path,
          recursive: chkRecursive.checked,
          hide_processed: chkHideProcessed.checked
        })
      });

      if (!res.ok) {
        const err = await res.json();
        alert(`Scan failed: ${err.detail || "Unknown error"}`);
        return;
      }

      const data = await res.json();
      scannedVideos = data.files || [];
      renderScannedTable();
    } catch (e) {
      alert(`Error during scan: ${e.message}`);
    } finally {
      btnScan.disabled = false;
      btnScan.textContent = "Scan Directory";
    }
  });

  // Master checkbox
  masterCheck.addEventListener("change", () => {
    document.querySelectorAll(".file-select-chk").forEach(chk => {
      chk.checked = masterCheck.checked;
    });
  });

  document.getElementById("btn-select-all").addEventListener("click", () => {
    masterCheck.checked = true;
    document.querySelectorAll(".file-select-chk").forEach(chk => chk.checked = true);
  });

  document.getElementById("btn-deselect-all").addEventListener("click", () => {
    masterCheck.checked = false;
    document.querySelectorAll(".file-select-chk").forEach(chk => chk.checked = false);
  });

  document.getElementById("btn-clear-logs").addEventListener("click", () => {
    document.getElementById("terminal-logs").innerHTML = "";
  });

  const btnDlLogs = document.getElementById("btn-download-logs-terminal");
  if (btnDlLogs) {
    btnDlLogs.addEventListener("click", () => {
      window.location.href = "/api/logs/download";
    });
  }

  const btnCopyLogs = document.getElementById("btn-copy-logs");
  if (btnCopyLogs) {
    btnCopyLogs.addEventListener("click", () => {
      const term = document.getElementById("terminal-logs");
      const lines = Array.from(term.querySelectorAll(".log-line"))
        .map(el => el.textContent.trim())
        .filter(Boolean);
      const textToCopy = lines.length > 0 ? lines.join("\n") : term.innerText.trim();
      if (!textToCopy) return;

      navigator.clipboard.writeText(textToCopy).then(() => {
        const orig = btnCopyLogs.textContent;
        btnCopyLogs.textContent = "✅ Copied!";
        setTimeout(() => { btnCopyLogs.textContent = orig; }, 2000);
      }).catch(() => {
        const ta = document.createElement("textarea");
        ta.value = textToCopy;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
        const orig = btnCopyLogs.textContent;
        btnCopyLogs.textContent = "✅ Copied!";
        setTimeout(() => { btnCopyLogs.textContent = orig; }, 2000);
      });
    });
  }
}

function renderScannedTable() {
  const tbody = document.getElementById("scanned-tbody");
  document.getElementById("found-count").textContent = scannedVideos.length;

  if (scannedVideos.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" class="empty-state">No matching video clips found in directory.</td></tr>`;
    return;
  }

  tbody.innerHTML = scannedVideos.map((v, idx) => {
    const statusBadge = v.has_sidecar 
      ? `<span class="badge-tag processed">Processed</span><div style="margin-top:6px;"><button class="btn-view-results" onclick="openResultsModal('${escapeHtml(v.path)}')">👁️ View Results</button></div>` 
      : `<span class="badge-tag unprocessed">Unprocessed</span>`;
      
    const srtBadge = v.has_srt 
      ? `<span class="badge-tag" style="background:#1e3a5f; color:#93c5fd; font-size:0.7rem; margin-left:6px;" title="Accompanying subtitle: ${escapeHtml(v.srt_filename || '')}">💬 .SRT paired</span>`
      : '';

    return `
      <tr>
        <td><input type="checkbox" class="file-select-chk" data-path="${escapeHtml(v.path)}" ${v.has_sidecar ? "" : "checked"}></td>
        <td><b>${escapeHtml(v.filename)}</b>${srtBadge}</td>
        <td class="text-muted"><small>${escapeHtml(v.parent_dir)}</small></td>
        <td>${v.size_formatted}</td>
        <td>${statusBadge}</td>
      </tr>
    `;
  }).join("");
}

// --- Conflict Resolution Modal (Already Processed Videos) ---
let pendingConflictResolution = null;

function initConflictModal() {
  const btnClose = document.getElementById("btn-close-conflict-modal");
  const btnCancel = document.getElementById("btn-conflict-cancel");
  const btnEnumerate = document.getElementById("btn-conflict-enumerate");
  const btnOverwrite = document.getElementById("btn-conflict-overwrite");

  if (btnClose) btnClose.addEventListener("click", closeConflictModal);
  if (btnCancel) btnCancel.addEventListener("click", closeConflictModal);

  if (btnEnumerate) {
    btnEnumerate.addEventListener("click", async () => {
      if (!pendingConflictResolution) return;
      const { filePaths, autoStart } = pendingConflictResolution;
      closeConflictModal();
      await executeQueueAdd(filePaths, "enumerate", autoStart);
    });
  }

  if (btnOverwrite) {
    btnOverwrite.addEventListener("click", async () => {
      if (!pendingConflictResolution) return;
      const { filePaths, autoStart } = pendingConflictResolution;
      closeConflictModal();
      await executeQueueAdd(filePaths, "overwrite", autoStart);
    });
  }
}

function openConflictModal(conflicts, filePaths, autoStart = false) {
  const modal = document.getElementById("modal-conflict-resolve");
  const listEl = document.getElementById("conflict-file-list");
  if (!modal || !listEl) return;

  pendingConflictResolution = { filePaths, autoStart };

  listEl.innerHTML = conflicts.map(c => `
    <div style="display:flex; justify-content:space-between; align-items:center; padding:5px 0; border-bottom:1px solid rgba(255,255,255,0.06); font-size:0.85rem;">
      <span style="font-weight:600; color:var(--text-main); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:65%;">📹 ${escapeHtml(c.filename)}</span>
      <span style="color:#94a3b8; font-size:0.75rem; background:rgba(255,255,255,0.05); padding:2px 6px; border-radius:4px;">${c.sidecars.join(', ')}</span>
    </div>
  `).join("");

  modal.classList.remove("hidden");
}

function closeConflictModal() {
  const modal = document.getElementById("modal-conflict-resolve");
  if (modal) modal.classList.add("hidden");
  pendingConflictResolution = null;
}

async function executeQueueAdd(filePaths, conflictMode, autoStart) {
  try {
    let dateOverride = null;
    let dateSource = null;
    const qDateSrcEl = document.getElementById("queue-date-source");
    if (qDateSrcEl) {
      dateSource = qDateSrcEl.value;
      if (dateSource === "override") {
        const dVal = document.getElementById("queue-date-override")?.value;
        const tVal = document.getElementById("queue-time-override")?.value;
        if (dVal) {
          dateOverride = tVal ? `${dVal}T${tVal}` : dVal;
        }
      }
    }

    let promptGuidance = document.getElementById("queue-prompt-guidance")?.value.trim() || undefined;

    const res = await fetch("/api/queue/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        file_paths: filePaths,
        conflict_mode: conflictMode,
        date_override: dateOverride,
        date_source: dateSource,
        prompt_guidance: promptGuidance
      })
    });
    if (!res.ok) {
      const err = await res.json();
      alert(`Error enqueuing: ${err.detail || res.statusText}`);
      return;
    }
    const data = await res.json();
    console.log(`Enqueued ${data.added_count} file(s) with conflict_mode=${conflictMode}`);
    
    if (autoStart) {
      await fetch("/api/queue/start", { method: "POST" });
    }
    pollStatus();
  } catch (e) {
    alert("Failed to enqueue files: " + e.message);
  }
}

async function requestEnqueueWithConflictCheck(filePaths, autoStart = false) {
  if (!filePaths || filePaths.length === 0) return;

  try {
    const res = await fetch("/api/queue/check-conflicts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file_paths: filePaths })
    });

    if (res.ok) {
      const data = await res.json();
      if (data.has_conflicts && data.conflicts && data.conflicts.length > 0) {
        openConflictModal(data.conflicts, filePaths, autoStart);
        return;
      }
    }
  } catch (err) {
    console.warn("Conflict check failed:", err);
  }

  // No conflict detected, proceed directly
  await executeQueueAdd(filePaths, "overwrite", autoStart);
}

// --- Queue Controls ---
function initQueueControls() {
  document.getElementById("btn-enqueue-selected").addEventListener("click", async () => {
    const selected = [];
    document.querySelectorAll(".file-select-chk:checked").forEach(chk => {
      selected.push(chk.dataset.path);
    });

    if (selected.length === 0) {
      alert("Please select at least one video clip.");
      return;
    }

    await requestEnqueueWithConflictCheck(selected, false);
  });

  document.getElementById("btn-queue-start").addEventListener("click", async () => {
    try {
      // 1. Check if the server queue currently has tasks waiting or running
      const statusRes = await fetch("/api/status");
      const statusData = statusRes.ok ? await statusRes.json() : null;
      const queueEmpty = !statusData || (statusData.counts.queued === 0 && statusData.counts.processing === 0);

      if (queueEmpty) {
        // Collect checked files from the scanned table
        let selected = [];
        document.querySelectorAll(".file-select-chk:checked").forEach(chk => {
          if (chk.dataset.path) selected.push(chk.dataset.path);
        });

        // If nothing was checked, but we have clips in the scanned table, select all clips
        if (selected.length === 0 && scannedVideos && scannedVideos.length > 0) {
          document.querySelectorAll(".file-select-chk").forEach(chk => {
            chk.checked = true;
            if (chk.dataset.path) selected.push(chk.dataset.path);
          });
          const masterCheck = document.getElementById("master-select");
          if (masterCheck) masterCheck.checked = true;
        }

        if (selected.length === 0) {
          alert("Queue is empty. Please scan a folder or select video clips first.");
          return;
        }

        // Auto-enqueue with conflict check and autoStart=true
        await requestEnqueueWithConflictCheck(selected, true);
        return;
      }

      await fetch("/api/queue/start", { method: "POST" });
      pollStatus();
    } catch (e) {
      console.error("Error starting queue:", e);
      await fetch("/api/queue/start", { method: "POST" });
      pollStatus();
    }
  });

  document.getElementById("btn-queue-pause").addEventListener("click", async () => {
    await fetch("/api/queue/pause", { method: "POST" });
    pollStatus();
  });

  const btnClearCompleted = document.getElementById("btn-queue-clear-completed");
  if (btnClearCompleted) {
    btnClearCompleted.addEventListener("click", async () => {
      await fetch("/api/queue/clear-completed", { method: "POST" });
      pollStatus();
    });
  }

  document.getElementById("btn-queue-clear").addEventListener("click", async () => {
    if (confirm("Clear all pending tasks from queue?")) {
      await fetch("/api/queue/clear", { method: "POST" });
      pollStatus();
    }
  });

  // Batch AI Guidance Presets & Actions
  const presetMap = {
    trip: "Vacation / Travel trip. Focus on scenic landmarks, beaches, mountains, cities, hotels, family members, local culture, activities, and transport (planes, trains, cars).",
    birthday: "Birthday celebration or party. Focus on the birthday person, blowing out candles, cake, opening gifts, family and friends gathered, laughter, decorations.",
    sports: "Athletic event, match, or practice. Focus on game action, key plays, scoreboards, team jerseys, players, coaches, courts, fields, and audience reactions.",
    home: "Casual everyday home footage or family time. Focus on family interactions, relaxing, cooking, backyard, living room activities, children playing.",
    pets: "Pets and domestic animals. Focus on pets (dogs, cats, etc.), their breeds/colors, behaviors, playing with toys, tricks, walks, interactions with owners."
  };

  const autoResizeGuidance = (el) => {
    if (!el) return;
    el.style.height = "auto";
    const nextH = Math.max(60, Math.min(el.scrollHeight + 4, 320));
    el.style.height = nextH + "px";
  };

  document.querySelectorAll(".btn-preset-guidance").forEach(btn => {
    btn.addEventListener("click", () => {
      const presetKey = btn.dataset.preset;
      const text = presetMap[presetKey];
      const textarea = document.getElementById("queue-prompt-guidance");
      if (textarea && text) {
        if (textarea.value.trim().length > 0) {
          textarea.value = textarea.value.trim() + "\n" + text;
        } else {
          textarea.value = text;
        }
        autoResizeGuidance(textarea);
        textarea.dispatchEvent(new Event("change"));
      }
    });
  });

  const btnClearGuidance = document.getElementById("btn-clear-queue-guidance");
  if (btnClearGuidance) {
    btnClearGuidance.addEventListener("click", () => {
      const textarea = document.getElementById("queue-prompt-guidance");
      if (textarea) {
        textarea.value = "";
        autoResizeGuidance(textarea);
        textarea.dispatchEvent(new Event("change"));
      }
    });
  }

  const btnSaveGuidanceDefault = document.getElementById("btn-save-guidance-as-default");
  if (btnSaveGuidanceDefault) {
    btnSaveGuidanceDefault.addEventListener("click", async () => {
      const currentVal = document.getElementById("queue-prompt-guidance")?.value.trim() || "";
      const cfgGuidanceEl = document.getElementById("cfg-default-prompt-guidance");
      if (cfgGuidanceEl) cfgGuidanceEl.value = currentVal;
      try {
        await fetch("/api/config", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ default_prompt_guidance: currentVal, batch_prompt_guidance: currentVal })
        });
        alert("Batch guidance saved as persistent default in Settings!");
      } catch (e) {
        console.error("Failed to save guidance as default:", e);
      }
    });
  }

  const queueGuidanceEl = document.getElementById("queue-prompt-guidance");
  if (queueGuidanceEl) {
    autoResizeGuidance(queueGuidanceEl);
    queueGuidanceEl.addEventListener("input", () => autoResizeGuidance(queueGuidanceEl));

    const syncBatchGuidance = async () => {
      try {
        await fetch("/api/queue/prompt-guidance", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ prompt_guidance: queueGuidanceEl.value.trim() })
        });
      } catch (e) {
        // silent fail
      }
    };
    queueGuidanceEl.addEventListener("change", syncBatchGuidance);
  }
}

// --- Settings & Connectors ---
let currentAppConfig = null;

function updateRenameSchemePreview() {
  const previewExampleEl = document.getElementById("cfg-rename-preview-example");
  const templateEl = document.getElementById("cfg-rename-template");
  const maxLenEl = document.getElementById("cfg-max-title-length");
  const includeNamesEl = document.getElementById("cfg-include-names");
  if (!previewExampleEl) return;
  const tpl = templateEl ? templateEl.value : "{date_compact}_{time_zulu}_{title}";
  
  const maxLen = maxLenEl ? parseInt(maxLenEl.value, 10) : 50;
  const includeNames = includeNamesEl ? includeNamesEl.checked : false;

  let rawTitle = "Kids_Birthday_Party";
  if (maxLen > 0 && rawTitle.length > maxLen) {
    rawTitle = rawTitle.slice(0, maxLen).replace(/[_\-]+$/, "");
  }

  const namesStr = "Grandma_Betty";
  let titleWithNames = rawTitle;
  if (includeNames && !tpl.includes("{names}") && !tpl.includes("{people}")) {
    titleWithNames = `${namesStr}_${rawTitle}`;
  }

  const sample = {
    date: "2024-05-18",
    date_compact: "20240518",
    year: "2024",
    month: "05",
    day: "18",
    time: "143000",
    time_compact: "143000",
    time_dashed: "14-30-00",
    time_zulu: "183000",
    time_zulu_dashed: "18-30-00",
    title: titleWithNames,
    names: namesStr,
    people: namesStr,
    original: "MVI_0042",
    folder: "Vacation",
    ai_slug: "kids_birthday_party"
  };
  let evaluated = tpl;
  for (const [k, v] of Object.entries(sample)) {
    evaluated = evaluated.replaceAll(`{${k}}`, v);
  }
  evaluated = evaluated.replace(/[^a-zA-Z0-9_\-]/g, "_").replace(/_+/g, "_").replace(/^_+|_+$/g, "");
  previewExampleEl.textContent = (evaluated || "video") + ".mp4";
}

async function loadConfig() {
  try {
    const res = await fetch("/api/config");
    if (!res.ok) return;
    const cfg = await res.json();
    currentAppConfig = cfg;

    const provSel = document.getElementById("cfg-vision-provider");
    provSel.value = cfg.vision_provider || "ollama";
    toggleProviderSections(provSel.value);

    document.getElementById("cfg-ollama-url").value = cfg.ollama_url || "http://localhost:11434";
    const ollamaModelSel = document.getElementById("cfg-ollama-model");
    if (ollamaModelSel) {
      const currentVal = cfg.ollama_model || "llama3.2-vision";
      // Ensure model exists as option
      const hasOption = Array.from(ollamaModelSel.options).some(o => o.value === currentVal);
      if (!hasOption) {
        const opt = document.createElement("option");
        opt.value = currentVal;
        opt.textContent = currentVal;
        ollamaModelSel.appendChild(opt);
      }
      ollamaModelSel.value = currentVal;
    }
    const ollamaNumCtxEl = document.getElementById("cfg-ollama-num-ctx");
    if (ollamaNumCtxEl) {
      ollamaNumCtxEl.value = cfg.ollama_num_ctx !== undefined ? cfg.ollama_num_ctx : 16384;
    }
    
    document.getElementById("cfg-openai-url").value = cfg.openai_compatible_url || "http://localhost:1234/v1";
    document.getElementById("cfg-openai-model").value = cfg.openai_compatible_model || "local-model";
    
    document.getElementById("cfg-cloud-provider").value = cfg.cloud_provider || "gemini";
    if (cfg.api_keys) {
      document.getElementById("cfg-cloud-key").value = cfg.api_keys[cfg.cloud_provider] || "";
    }
    const transcribeAudioEl = document.getElementById("cfg-transcribe-audio");
    if (transcribeAudioEl) transcribeAudioEl.checked = cfg.transcribe_audio !== false;

    const whisperBackendEl = document.getElementById("cfg-whisper-backend");
    const backendVal = cfg.whisper_backend || "faster-whisper";
    if (whisperBackendEl) {
      whisperBackendEl.value = backendVal;
      toggleWhisperBackendSections(backendVal);
    }

    const whisperRemoteUrlEl = document.getElementById("cfg-whisper-remote-url");
    if (whisperRemoteUrlEl) whisperRemoteUrlEl.value = cfg.whisper_remote_url || "";

    const whisperApiKeyEl = document.getElementById("cfg-whisper-api-key");
    if (whisperApiKeyEl) whisperApiKeyEl.value = cfg.whisper_api_key || "";

    const whisperRemoteModelEl = document.getElementById("cfg-whisper-remote-model");
    if (whisperRemoteModelEl) whisperRemoteModelEl.value = cfg.whisper_model || "base";

    const whisperLocalModelEl = document.getElementById("cfg-whisper-model");
    if (whisperLocalModelEl) whisperLocalModelEl.value = cfg.whisper_model || "base";

    // Pipeline Execution Mode
    const pipeModeEl = document.getElementById("cfg-pipeline-execution-mode");
    if (pipeModeEl) pipeModeEl.value = cfg.processing_execution_mode || "serial";

    // Long Video Sampling Settings
    const sampStratEl = document.getElementById("cfg-sampling-strategy");
    if (sampStratEl) {
      sampStratEl.value = cfg.sampling_strategy || "interval";
      toggleSamplingStrategyFields(sampStratEl.value);
    }
    const sampIntEl = document.getElementById("cfg-sampling-interval");
    if (sampIntEl) {
      sampIntEl.value = String(cfg.sampling_interval_seconds || 60);
    }
    const maxFramesEl = document.getElementById("cfg-max-frames");
    const badgeMaxFrames = document.getElementById("badge-max-frames");
    if (maxFramesEl) {
      maxFramesEl.value = cfg.max_frames_per_video || 30;
      if (badgeMaxFrames) badgeMaxFrames.textContent = `${maxFramesEl.value} frames`;
    }

    // Subtitle Settings
    const useSubEl = document.getElementById("cfg-use-subtitles");
    if (useSubEl) useSubEl.checked = cfg.use_subtitles !== false;
    const prefSubEl = document.getElementById("cfg-prefer-subtitles");
    if (prefSubEl) prefSubEl.checked = cfg.prefer_subtitles_over_whisper !== false;
    const fullTransFallbackEl = document.getElementById("cfg-full-transcription-fallback");
    if (fullTransFallbackEl) fullTransFallbackEl.checked = cfg.full_transcription_if_no_subtitles !== false;

    // Face Recognition Settings
    const faceEnabledEl = document.getElementById("cfg-face-enabled");
    if (faceEnabledEl) faceEnabledEl.checked = cfg.face_recognition_enabled || false;
    const faceProvEl = document.getElementById("cfg-face-provider");
    if (faceProvEl) {
      faceProvEl.value = cfg.face_provider || "builtin";
      toggleFaceProviderSections(faceProvEl.value);
    }
    const confVal = cfg.face_detection_confidence !== undefined ? cfg.face_detection_confidence : 0.70;
    const faceConfEl = document.getElementById("cfg-face-confidence");
    const badgeConfEl = document.getElementById("badge-face-confidence");
    const quickConfEl = document.getElementById("faces-quick-confidence");
    const badgeQuickConfEl = document.getElementById("badge-faces-quick-confidence");
    if (faceConfEl) faceConfEl.value = confVal;
    if (badgeConfEl) badgeConfEl.textContent = Number(confVal).toFixed(2);
    if (quickConfEl) quickConfEl.value = confVal;
    if (badgeQuickConfEl) badgeQuickConfEl.textContent = Number(confVal).toFixed(2);
    updateFaceSensitivityBadge(confVal);

    const distVal = cfg.face_max_distance !== undefined ? cfg.face_max_distance : 0.45;
    const faceDistEl = document.getElementById("cfg-face-distance");
    const badgeDistEl = document.getElementById("badge-face-distance");
    const quickDistEl = document.getElementById("faces-quick-distance");
    const badgeQuickDistEl = document.getElementById("badge-faces-quick-distance");
    if (faceDistEl) faceDistEl.value = distVal;
    if (badgeDistEl) badgeDistEl.textContent = `Distance: ${Number(distVal).toFixed(2)} (Similarity: ${Math.max(0, 1 - Number(distVal)).toFixed(2)})`;
    if (quickDistEl) quickDistEl.value = distVal;
    if (badgeQuickDistEl) badgeQuickDistEl.textContent = `Distance: ${Number(distVal).toFixed(2)} (Similarity: ${Math.max(0, 1 - Number(distVal)).toFixed(2)})`;
    const comprefaceUrlEl = document.getElementById("cfg-compreface-url");
    if (comprefaceUrlEl) comprefaceUrlEl.value = cfg.compreface_url || "http://localhost:8000";
    const comprefaceKeyEl = document.getElementById("cfg-compreface-key");
    if (comprefaceKeyEl) comprefaceKeyEl.value = cfg.compreface_api_key || "";

    // Metadata Presets & Sidecar Formats
    const metaPresetEl = document.getElementById("cfg-metadata-preset");
    if (metaPresetEl) metaPresetEl.value = cfg.metadata_preset || "all";
    const exportNfoEl = document.getElementById("cfg-export-nfo");
    if (exportNfoEl) exportNfoEl.checked = cfg.export_nfo !== false;

    document.getElementById("cfg-export-txt").checked = cfg.export_txt;
    document.getElementById("cfg-export-json").checked = cfg.export_info_json;
    document.getElementById("cfg-export-xmp").checked = cfg.export_xmp;
    const exportSrtEl = document.getElementById("cfg-export-srt");
    if (exportSrtEl) exportSrtEl.checked = cfg.export_srt !== false;
    document.getElementById("cfg-export-edl").checked = cfg.export_edl;
    document.getElementById("cfg-enable-tagging").checked = cfg.enable_in_file_tagging;

    const retentionEl = document.getElementById("cfg-temp-retention");
    if (retentionEl) retentionEl.value = cfg.temp_retention_policy || "immediate";

    // Auto-actions & Renaming Scheme
    const autoRenameEl = document.getElementById("cfg-auto-rename");
    if (autoRenameEl) autoRenameEl.checked = !!cfg.auto_rename;
    const quickRenameToggle = document.getElementById("quick-auto-rename-toggle");
    const quickRenameLabel = document.getElementById("quick-auto-rename-label");
    if (quickRenameToggle) {
      quickRenameToggle.checked = !!cfg.auto_rename;
      if (quickRenameLabel) {
        quickRenameLabel.textContent = cfg.auto_rename ? "ON" : "OFF";
        quickRenameLabel.style.color = cfg.auto_rename ? "#34d399" : "#94a3b8";
      }
    }
    const autoTagEl = document.getElementById("cfg-auto-tag");
    if (autoTagEl) autoTagEl.checked = !!cfg.enable_in_file_tagging;
    const enableTagEl = document.getElementById("cfg-enable-tagging");
    if (enableTagEl) enableTagEl.checked = !!cfg.enable_in_file_tagging;
    const backupTagEl = document.getElementById("cfg-backup-before-tagging");
    if (backupTagEl) backupTagEl.checked = cfg.backup_before_tagging !== false;
    const flushBackupEl = document.getElementById("cfg-flush-backup-on-success");
    if (flushBackupEl) flushBackupEl.checked = cfg.flush_backup_on_success !== false;
    const flushBackupQuickEl = document.getElementById("cfg-flush-backup-quick");
    if (flushBackupQuickEl) flushBackupQuickEl.checked = cfg.flush_backup_on_success !== false;
    const verifyTagEl = document.getElementById("cfg-verify-tag-integrity");
    if (verifyTagEl) verifyTagEl.checked = cfg.verify_integrity !== false;
    const schemeEl = document.getElementById("cfg-rename-scheme");
    if (schemeEl) schemeEl.value = cfg.rename_scheme || "compact_zulu_title";
    const templateEl = document.getElementById("cfg-rename-template");
    if (templateEl) templateEl.value = cfg.rename_template || "{date_compact}_{time_zulu}_{title}";
    const maxLenEl = document.getElementById("cfg-max-title-length");
    if (maxLenEl && cfg.max_title_length !== undefined) maxLenEl.value = String(cfg.max_title_length);
    const incNamesEl = document.getElementById("cfg-include-names");
    if (incNamesEl) incNamesEl.checked = !!cfg.include_names_in_title;
    const dateSourceEl = document.getElementById("cfg-date-source");
    if (dateSourceEl) dateSourceEl.value = cfg.date_source || "smart";
    const dateOverrideEl = document.getElementById("cfg-default-date-override");
    if (dateOverrideEl) dateOverrideEl.value = cfg.default_date_override || "";

    // Prompt Guidance & Custom System Prompt
    const defaultGuidanceEl = document.getElementById("cfg-default-prompt-guidance");
    if (defaultGuidanceEl) defaultGuidanceEl.value = cfg.default_prompt_guidance || "";

    const customSystemPromptEl = document.getElementById("cfg-custom-system-prompt");
    if (customSystemPromptEl) customSystemPromptEl.value = cfg.custom_system_prompt || "";

    const aiTimeoutEl = document.getElementById("cfg-ai-timeout");
    if (aiTimeoutEl) aiTimeoutEl.value = cfg.ai_timeout_seconds || 600;

    const queueGuidanceEl = document.getElementById("queue-prompt-guidance");
    if (queueGuidanceEl && !queueGuidanceEl.value) {
      queueGuidanceEl.value = cfg.batch_prompt_guidance || "";
    }
    if (queueGuidanceEl) {
      queueGuidanceEl.dispatchEvent(new Event("input"));
    }

    updateRenameSchemePreview();

    // Load Whisper model storage info
    try {
      const wRes = await fetch("/api/models/whisper");
      if (wRes.ok) {
        const wData = await wRes.json();
        const pEl = document.getElementById("whisper-cache-path");
        if (pEl) pEl.textContent = wData.models_dir || "Self-contained";

        const statusText = document.getElementById("whisper-engine-status-text");
        const installBtn = document.getElementById("btn-install-whisper");
        const statusBanner = document.getElementById("whisper-engine-status-banner");

        if (wData.faster_whisper) {
          if (statusText) statusText.innerHTML = `✅ <strong>Local Engine Installed</strong>: <code>faster-whisper</code> is ready for offline speech recognition.`;
          if (statusBanner) {
            statusBanner.style.borderColor = "rgba(16, 185, 129, 0.4)";
            statusBanner.style.background = "rgba(6, 78, 59, 0.3)";
          }
          if (installBtn) installBtn.classList.add("hidden");
        } else {
          if (statusText) statusText.innerHTML = `⚠️ <strong>faster-whisper is not installed</strong> in the Python environment.`;
          if (statusBanner) {
            statusBanner.style.borderColor = "rgba(245, 158, 11, 0.4)";
            statusBanner.style.background = "rgba(120, 53, 15, 0.3)";
          }
          if (installBtn) {
            installBtn.classList.remove("hidden");
            installBtn.disabled = false;
            installBtn.textContent = "⚡ Install faster-whisper Engine";
          }
        }

        const tagsEl = document.getElementById("whisper-downloaded-tags");
        if (tagsEl) {
          const dl = wData.downloaded_models || [];
          if (dl.length > 0) {
            tagsEl.innerHTML = `<span style="font-size:0.75rem;">Downloaded: </span>` + dl.map(m => `<span class="model-tag">${escapeHtml(m)}</span>`).join("");
          } else {
            const hint = wData.faster_whisper ? "will download automatically on first run" : "install engine above first";
            tagsEl.innerHTML = `<span style="font-size:0.75rem;" class="text-muted">No models cached yet (${hint})</span>`;
          }
        }
      }
    } catch (we) {
      console.warn("Whisper info check failed:", we);
    }

    // Load Custom FFmpeg paths
    const ffmpegInput = document.getElementById("cfg-ffmpeg-path");
    if (ffmpegInput) ffmpegInput.value = cfg.ffmpeg_path || "";
    const ffprobeInput = document.getElementById("cfg-ffprobe-path");
    if (ffprobeInput) ffprobeInput.value = cfg.ffprobe_path || "";

    // Check health & FFmpeg
    checkAIHealth();
    checkFFmpegStatus();
  } catch (err) {
    console.error("Failed to load config:", err);
  }
}

// --- FFmpeg Status & In-App Installation ---
async function checkFFmpegStatus() {
  const badge = document.getElementById("ffmpeg-status-indicator");
  const banner = document.getElementById("ffmpeg-warning-banner");
  const ffmpegStatus = document.getElementById("ffmpeg-detected-status");
  const ffmpegPath = document.getElementById("ffmpeg-detected-path");
  const ffprobeStatus = document.getElementById("ffprobe-detected-status");
  const ffprobePath = document.getElementById("ffprobe-detected-path");

  try {
    const res = await fetch("/api/ffmpeg/status");
    if (!res.ok) return;
    const data = await res.json();

    if (data.all_ready) {
      if (badge) {
        badge.className = "status-badge connected";
        badge.textContent = "FFmpeg: Ready";
      }
      if (banner) banner.classList.add("hidden");
    } else {
      if (badge) {
        badge.className = "status-badge error";
        badge.textContent = "FFmpeg: Missing";
      }
      if (banner) banner.classList.remove("hidden");
    }

    if (ffmpegStatus) {
      ffmpegStatus.className = `badge-tag ${data.ffmpeg.available ? "processed" : "danger"}`;
      ffmpegStatus.textContent = data.ffmpeg.available ? "Available" : "Not Found";
    }
    if (ffmpegPath) {
      ffmpegPath.textContent = data.ffmpeg.available ? `${data.ffmpeg.path}` : "";
      if (data.ffmpeg.version) ffmpegPath.title = data.ffmpeg.version;
    }

    if (ffprobeStatus) {
      ffprobeStatus.className = `badge-tag ${data.ffprobe.available ? "processed" : "danger"}`;
      ffprobeStatus.textContent = data.ffprobe.available ? "Available" : "Not Found";
    }
    if (ffprobePath) {
      ffprobePath.textContent = data.ffprobe.available ? `${data.ffprobe.path}` : "";
      if (data.ffprobe.version) ffprobePath.title = data.ffprobe.version;
    }

  } catch (err) {
    console.error("FFmpeg check failed:", err);
  }
}

function initSettings() {
  const provSel = document.getElementById("cfg-vision-provider");
  provSel.addEventListener("change", () => {
    toggleProviderSections(provSel.value);
  });

  const schemeEl = document.getElementById("cfg-rename-scheme");
  const templateEl = document.getElementById("cfg-rename-template");
  if (schemeEl && templateEl) {
    schemeEl.addEventListener("change", () => {
      const scheme = schemeEl.value;
      if (scheme === "compact_zulu_title") templateEl.value = "{date_compact}_{time_zulu}_{title}";
      else if (scheme === "compact_zulu_names_title") templateEl.value = "{date_compact}_{time_zulu}_{names}_{title}";
      else if (scheme === "compact_time_title") templateEl.value = "{date_compact}_{time}_{title}";
      else if (scheme === "compact_dashed_time_title") templateEl.value = "{date_compact}_{time_dashed}_{title}";
      else if (scheme === "compact_date_title") templateEl.value = "{date_compact}_{title}";
      else if (scheme === "date_title") templateEl.value = "{date}_{title}";
      else if (scheme === "date_time_title") templateEl.value = "{date}_{time}_{title}";
      else if (scheme === "folder_date_title") templateEl.value = "{folder}_{date}_{title}";
      else if (scheme === "original_title") templateEl.value = "{original}_{title}";
      else if (scheme === "title_only") templateEl.value = "{title}";
      else if (scheme === "ai_slug") templateEl.value = "{ai_slug}";
      updateRenameSchemePreview();
    });
    templateEl.addEventListener("input", updateRenameSchemePreview);
  }

  const maxLenEl = document.getElementById("cfg-max-title-length");
  if (maxLenEl) maxLenEl.addEventListener("change", updateRenameSchemePreview);

  const incNamesEl = document.getElementById("cfg-include-names");
  if (incNamesEl) incNamesEl.addEventListener("change", updateRenameSchemePreview);

  // Verify custom paths button
  const btnVerify = document.getElementById("btn-verify-ffmpeg-paths");
  if (btnVerify) {
    btnVerify.addEventListener("click", async () => {
      const ffmpegPath = document.getElementById("cfg-ffmpeg-path").value.trim();
      const ffprobePath = document.getElementById("cfg-ffprobe-path").value.trim();
      const resultEl = document.getElementById("verify-ffmpeg-result");

      resultEl.textContent = "Testing...";
      try {
        const res = await fetch("/api/ffmpeg/verify", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ffmpeg_path: ffmpegPath, ffprobe_path: ffprobePath })
        });
        const data = await res.json();
        const fOk = data.ffmpeg.available;
        const pOk = data.ffprobe.available;

        if (fOk && pOk) {
          resultEl.innerHTML = `<span style="color:#34d399;">✓ Both binaries valid!</span>`;
        } else {
          resultEl.innerHTML = `<span style="color:#f87171;">FFmpeg: ${fOk ? '✓' : '✗'}, FFprobe: ${pOk ? '✓' : '✗'}</span>`;
        }
      } catch (e) {
        resultEl.textContent = "Error testing paths: " + e.message;
      }
    });
  }

  // Ollama test button
  document.getElementById("btn-test-ollama").addEventListener("click", async () => {
    const btn = document.getElementById("btn-test-ollama");
    btn.disabled = true;
    btn.textContent = "Connecting...";

    try {
      const res = await fetch("/api/models/ollama");
      const data = await res.json();
      if (data.connected) {
        alert(`Ollama connected successfully! Found ${data.models.length} model(s).`);
        // Populate model dropdown
        const sel = document.getElementById("cfg-ollama-model");
        if (data.models.length > 0) {
          sel.innerHTML = data.models.map(m => `<option value="${escapeHtml(m)}">${escapeHtml(m)}</option>`).join("");
        }
      } else {
        alert(`Could not connect to Ollama at ${data.url}. Make sure Ollama is running ('ollama serve').`);
      }
    } catch (e) {
      alert("Connection test error: " + e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = "Test & Refresh Models";
      checkAIHealth();
    }
  });

  // OpenAI / LM Studio test button
  document.getElementById("btn-test-openai").addEventListener("click", async () => {
    const btn = document.getElementById("btn-test-openai");
    btn.disabled = true;
    btn.textContent = "Connecting...";

    try {
      const res = await fetch("/api/models/openai");
      const data = await res.json();
      if (data.connected) {
        alert(`LM Studio / OpenAI server connected successfully! Found ${data.models.length} model(s).`);
      } else {
        alert(`Could not connect to server at ${data.url}.`);
      }
    } catch (e) {
      alert("Connection test error: " + e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = "Test Connection";
      checkAIHealth();
    }
  });

  // Save Config
  document.getElementById("btn-save-config").addEventListener("click", async () => {
    const visionProv = document.getElementById("cfg-vision-provider").value;
    const cloudProv = document.getElementById("cfg-cloud-provider").value;
    const cloudKey = document.getElementById("cfg-cloud-key").value;

    const payload = {
      ffmpeg_path: document.getElementById("cfg-ffmpeg-path").value.trim() || null,
      ffprobe_path: document.getElementById("cfg-ffprobe-path").value.trim() || null,
      vision_provider: visionProv,
      ollama_url: document.getElementById("cfg-ollama-url").value.trim(),
      ollama_model: document.getElementById("cfg-ollama-model").value,
      ollama_num_ctx: parseInt(document.getElementById("cfg-ollama-num-ctx")?.value || "16384", 10),
      openai_compatible_url: document.getElementById("cfg-openai-url").value.trim(),
      openai_compatible_model: document.getElementById("cfg-openai-model").value.trim(),
      cloud_provider: cloudProv,
      transcribe_audio: document.getElementById("cfg-transcribe-audio")?.checked ?? true,
      whisper_backend: document.getElementById("cfg-whisper-backend")?.value || "faster-whisper",
      whisper_remote_url: document.getElementById("cfg-whisper-remote-url")?.value.trim() || null,
      whisper_api_key: document.getElementById("cfg-whisper-api-key")?.value.trim() || "",
      whisper_model: (document.getElementById("cfg-whisper-backend")?.value === "remote")
        ? (document.getElementById("cfg-whisper-remote-model")?.value.trim() || "base")
        : (document.getElementById("cfg-whisper-model")?.value || "base"),
      face_recognition_enabled: document.getElementById("cfg-face-enabled")?.checked || false,
      face_provider: document.getElementById("cfg-face-provider")?.value || "builtin",
      face_detection_confidence: parseFloat(document.getElementById("cfg-face-confidence")?.value || "0.70"),
      face_max_distance: parseFloat(document.getElementById("cfg-face-distance")?.value || "0.45"),
      face_match_threshold: 1.0 - parseFloat(document.getElementById("cfg-face-distance")?.value || "0.45"),
      compreface_url: document.getElementById("cfg-compreface-url")?.value.trim() || "",
      compreface_api_key: document.getElementById("cfg-compreface-key")?.value.trim() || "",
      processing_execution_mode: document.getElementById("cfg-pipeline-execution-mode")?.value || "serial",
      use_subtitles: document.getElementById("cfg-use-subtitles")?.checked ?? true,
      prefer_subtitles_over_whisper: document.getElementById("cfg-prefer-subtitles")?.checked ?? true,
      full_transcription_if_no_subtitles: document.getElementById("cfg-full-transcription-fallback")?.checked ?? true,
      export_nfo: document.getElementById("cfg-export-nfo")?.checked ?? true,
      export_txt: document.getElementById("cfg-export-txt").checked,
      export_info_json: document.getElementById("cfg-export-json").checked,
      export_xmp: document.getElementById("cfg-export-xmp").checked,
      export_srt: document.getElementById("cfg-export-srt")?.checked ?? true,
      export_edl: document.getElementById("cfg-export-edl")?.checked ?? false,
      enable_in_file_tagging: document.getElementById("cfg-auto-tag")?.checked || document.getElementById("cfg-enable-tagging")?.checked || false,
      backup_before_tagging: document.getElementById("cfg-backup-before-tagging")?.checked ?? true,
      flush_backup_on_success: (document.getElementById("cfg-flush-backup-on-success")?.checked ?? document.getElementById("cfg-flush-backup-quick")?.checked ?? true),
      verify_integrity: document.getElementById("cfg-verify-tag-integrity")?.checked ?? true,
      auto_rename: document.getElementById("cfg-auto-rename")?.checked || false,
      rename_scheme: document.getElementById("cfg-rename-scheme")?.value || "date_title",
      rename_template: document.getElementById("cfg-rename-template")?.value.trim() || "{date}_{title}",
      max_title_length: parseInt(document.getElementById("cfg-max-title-length")?.value || "50", 10),
      include_names_in_title: document.getElementById("cfg-include-names")?.checked || false,
      date_source: document.getElementById("cfg-date-source")?.value || "smart",
      default_date_override: document.getElementById("cfg-default-date-override")?.value.trim() || null,
      temp_retention_policy: document.getElementById("cfg-temp-retention") ? document.getElementById("cfg-temp-retention").value : "immediate",
      sampling_strategy: document.getElementById("cfg-sampling-strategy")?.value || "interval",
      sampling_interval_seconds: parseInt(document.getElementById("cfg-sampling-interval")?.value || "60", 10),
      max_frames_per_video: parseInt(document.getElementById("cfg-max-frames")?.value || "30", 10),
      ai_timeout_seconds: parseInt(document.getElementById("cfg-ai-timeout")?.value || "600", 10),
      default_prompt_guidance: document.getElementById("cfg-default-prompt-guidance")?.value.trim() || "",
      custom_system_prompt: document.getElementById("cfg-custom-system-prompt")?.value.trim() || "",
      batch_prompt_guidance: document.getElementById("queue-prompt-guidance")?.value.trim() || ""
    };

    try {
      const res = await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        const statusEl = document.getElementById("save-config-status");
        if (statusEl) {
          statusEl.classList.remove("hidden");
          setTimeout(() => statusEl.classList.add("hidden"), 3000);
        }
        await loadConfig();
        checkAIHealth();
        checkFFmpegStatus();
      } else {
        const err = await res.json();
        alert("Failed to save settings: " + (err.detail || JSON.stringify(err)));
      }
    } catch (e) {
      alert("Failed to save settings: " + e.message);
    }
  });

  // Wire Reset System Prompt Button
  const btnResetPrompt = document.getElementById("btn-reset-system-prompt");
  if (btnResetPrompt) {
    btnResetPrompt.addEventListener("click", async () => {
      try {
        const res = await fetch("/api/prompts/defaults");
        if (res.ok) {
          const data = await res.json();
          const area = document.getElementById("cfg-custom-system-prompt");
          if (area) {
            area.value = data.default_system_prompt || "";
          }
          const status = document.getElementById("system-prompt-status");
          if (status) {
            status.textContent = "Reset to default. Remember to click Save Settings.";
            setTimeout(() => { status.textContent = ""; }, 4000);
          }
        }
      } catch (e) {
        console.error("Failed to fetch default system prompt:", e);
      }
    });
  }

  // Wire Whisper backend toggle
  const whisperBackendEl = document.getElementById("cfg-whisper-backend");
  if (whisperBackendEl) {
    whisperBackendEl.addEventListener("change", (e) => {
      toggleWhisperBackendSections(e.target.value);
    });
  }

  // Wire Remote Whisper connection test button
  const btnTestWhisper = document.getElementById("btn-test-whisper-remote");
  if (btnTestWhisper) {
    btnTestWhisper.addEventListener("click", async () => {
      const statusEl = document.getElementById("whisper-remote-test-status");
      const urlInput = document.getElementById("cfg-whisper-remote-url");
      const keyInput = document.getElementById("cfg-whisper-api-key");
      const modelInput = document.getElementById("cfg-whisper-remote-model");

      const url = urlInput ? urlInput.value.trim() : "";
      if (!url) {
        alert("Please enter a Whisper server address with port (e.g. http://192.168.1.100:9000).");
        if (urlInput) urlInput.focus();
        return;
      }

      btnTestWhisper.disabled = true;
      btnTestWhisper.textContent = "Connecting...";
      if (statusEl) {
        statusEl.textContent = "Connecting to Whisper server...";
        statusEl.style.color = "#94a3b8";
      }

      try {
        const res = await fetch("/api/whisper/test-remote", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            url: url,
            api_key: keyInput ? keyInput.value.trim() : "",
            model: modelInput ? modelInput.value.trim() : "base"
          })
        });
        const data = await res.json();
        if (res.ok && data.status === "ok") {
          if (statusEl) {
            statusEl.textContent = `✅ ${data.message}`;
            statusEl.style.color = "#34d399";
          }
          // Populate datalist if server returned models
          if (Array.isArray(data.models) && data.models.length > 0) {
            const datalist = document.getElementById("whisper-remote-models-datalist");
            if (datalist) {
              datalist.innerHTML = data.models.map(m => `<option value="${escapeHtml(m)}">`).join("");
            }
          }
        } else {
          if (statusEl) {
            statusEl.textContent = `❌ ${data.message || data.detail || "Connection failed"}`;
            statusEl.style.color = "#f87171";
          }
        }
      } catch (err) {
        if (statusEl) {
          statusEl.textContent = `❌ Test error: ${err.message}`;
          statusEl.style.color = "#f87171";
        }
      } finally {
        btnTestWhisper.disabled = false;
        btnTestWhisper.textContent = "⚡ Test Connection & Fetch Models";
      }
    });
  }

  // Wire In-App Whisper Engine Installation
  const btnInstallWhisper = document.getElementById("btn-install-whisper");
  if (btnInstallWhisper) {
    btnInstallWhisper.addEventListener("click", async () => {
      const statusText = document.getElementById("whisper-engine-status-text");
      btnInstallWhisper.disabled = true;
      btnInstallWhisper.textContent = "⏳ Installing...";
      if (statusText) statusText.innerHTML = `⏳ Downloading and installing <code>faster-whisper</code> into Python environment... please wait 1-2 minutes.`;
      try {
        const res = await fetch("/api/whisper/install", { method: "POST" });
        const data = await res.json();
        if (res.ok) {
          showToast("faster-whisper engine installed successfully!", "success");
          loadConfig();
        } else {
          showToast("Failed to install faster-whisper: " + (data.detail || "Error"), "error");
          btnInstallWhisper.disabled = false;
          btnInstallWhisper.textContent = "⚡ Retry Installation";
        }
      } catch (err) {
        showToast("Error installing faster-whisper: " + err.message, "error");
        btnInstallWhisper.disabled = false;
        btnInstallWhisper.textContent = "⚡ Retry Installation";
      }
    });
  }

  // Wire face provider toggle
  const faceProvEl = document.getElementById("cfg-face-provider");
  if (faceProvEl) {
    faceProvEl.addEventListener("change", (e) => {
      toggleFaceProviderSections(e.target.value);
    });
  }

  // Wire CompreFace connection test button
  const btnTestCompreface = document.getElementById("btn-test-compreface");
  if (btnTestCompreface) {
    btnTestCompreface.addEventListener("click", async () => {
      const statusEl = document.getElementById("compreface-test-status");
      statusEl.textContent = "Connecting to CompreFace...";
      try {
        const res = await fetch("/api/faces/test-external", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            url: document.getElementById("cfg-compreface-url").value.trim(),
            api_key: document.getElementById("cfg-compreface-key").value.trim()
          })
        });
        const data = await res.json();
        if (data.status === "ok") {
          statusEl.textContent = `✅ ${data.message}`;
          statusEl.style.color = "#34d399";
        } else {
          statusEl.textContent = `❌ ${data.message}`;
          statusEl.style.color = "#f87171";
        }
      } catch (err) {
        statusEl.textContent = `❌ Test failed: ${err.message}`;
        statusEl.style.color = "#f87171";
      }
    });
  }

  // Wire Built-in Face Detection Sensitivity & Clustering Sliders
  const faceConfEl = document.getElementById("cfg-face-confidence");
  const badgeConfEl = document.getElementById("badge-face-confidence");
  if (faceConfEl) {
    faceConfEl.addEventListener("input", (e) => {
      const v = parseFloat(e.target.value).toFixed(2);
      if (badgeConfEl) badgeConfEl.textContent = v;
      const quickConf = document.getElementById("faces-quick-confidence");
      const badgeQuickConf = document.getElementById("badge-faces-quick-confidence");
      if (quickConf) quickConf.value = v;
      if (badgeQuickConf) badgeQuickConf.textContent = v;
      updateFaceSensitivityBadge(v);
    });
  }

  const faceDistEl = document.getElementById("cfg-face-distance");
  const badgeDistEl = document.getElementById("badge-face-distance");
  if (faceDistEl) {
    faceDistEl.addEventListener("input", (e) => {
      const dist = parseFloat(e.target.value);
      const text = `Distance: ${dist.toFixed(2)} (Similarity: ${Math.max(0, 1 - dist).toFixed(2)})`;
      if (badgeDistEl) badgeDistEl.textContent = text;
      const quickDist = document.getElementById("faces-quick-distance");
      const badgeQuickDist = document.getElementById("badge-faces-quick-distance");
      if (quickDist) quickDist.value = dist;
      if (badgeQuickDist) badgeQuickDist.textContent = text;
    });
  }

  // Wire People & Faces sensitivity badge shortcut
  const facesSensBadge = document.getElementById("faces-sensitivity-badge");
  if (facesSensBadge) {
    facesSensBadge.addEventListener("click", () => {
      const tabBtn = document.querySelector('.nav-tab[data-tab="tab-connectors"]');
      if (tabBtn) tabBtn.click();
      const targetInput = document.getElementById("cfg-face-confidence");
      if (targetInput) {
        targetInput.scrollIntoView({ behavior: "smooth", block: "center" });
        targetInput.focus();
      }
    });
  }

  // Wire Sampling Strategy & Interval
  const sampStratEl = document.getElementById("cfg-sampling-strategy");
  if (sampStratEl) {
    sampStratEl.addEventListener("change", (e) => {
      toggleSamplingStrategyFields(e.target.value);
    });
  }

  const maxFramesEl = document.getElementById("cfg-max-frames");
  const badgeMaxFrames = document.getElementById("badge-max-frames");
  if (maxFramesEl && badgeMaxFrames) {
    maxFramesEl.addEventListener("input", (e) => {
      badgeMaxFrames.textContent = `${e.target.value} frames`;
    });
  }

  // Mobile video picker tap
  const btnMobilePick = document.getElementById("btn-mobile-pick");
  const filePickerEl = document.getElementById("file-picker");
  if (btnMobilePick && filePickerEl) {
    btnMobilePick.addEventListener("click", () => {
      filePickerEl.click();
    });
  }

  // Download Video Options Modal listeners
  const btnCloseDlModal = document.getElementById("btn-close-download-modal");
  const btnCancelDlModal = document.getElementById("btn-cancel-download-modal");
  if (btnCloseDlModal) btnCloseDlModal.addEventListener("click", closeDownloadModal);
  if (btnCancelDlModal) btnCancelDlModal.addEventListener("click", closeDownloadModal);

  const btnConfirmDl = document.getElementById("btn-confirm-download-video");
  if (btnConfirmDl) btnConfirmDl.addEventListener("click", executeCustomDownload);

  // Filename radio toggle
  document.querySelectorAll('input[name="dl-filename-choice"]').forEach(radio => {
    radio.addEventListener("change", (e) => {
      const customInput = document.getElementById("dl-input-custom-name");
      if (customInput) {
        if (e.target.value === "custom") {
          customInput.classList.remove("hidden");
          customInput.focus();
        } else {
          customInput.classList.add("hidden");
        }
      }
    });
  });

  // Interactive Object Tagging button & input
  const btnAddObj = document.getElementById("btn-add-object-tag");
  const inputAddObj = document.getElementById("input-new-object-tag");
  if (btnAddObj) btnAddObj.addEventListener("click", addObjectTag);
  if (inputAddObj) {
    inputAddObj.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        addObjectTag();
      }
    });
  }

  // Wire Metadata Preset dropdown
  const metaPresetEl = document.getElementById("cfg-metadata-preset");
  if (metaPresetEl) {
    metaPresetEl.addEventListener("change", (e) => {
      const val = e.target.value;
      const nfoChk = document.getElementById("cfg-export-nfo");
      const xmpChk = document.getElementById("cfg-export-xmp");
      const txtChk = document.getElementById("cfg-export-txt");
      const jsonChk = document.getElementById("cfg-export-json");
      const srtChk = document.getElementById("cfg-export-srt");
      const edlChk = document.getElementById("cfg-export-edl");

      if (val === "all") {
        if (nfoChk) nfoChk.checked = true;
        if (xmpChk) xmpChk.checked = true;
        if (txtChk) txtChk.checked = true;
        if (jsonChk) jsonChk.checked = true;
        if (srtChk) srtChk.checked = true;
        if (edlChk) edlChk.checked = true;
      } else if (val === "jellyfin") {
        if (nfoChk) nfoChk.checked = true;
        if (xmpChk) xmpChk.checked = false;
        if (txtChk) txtChk.checked = true;
        if (jsonChk) jsonChk.checked = true;
        if (srtChk) srtChk.checked = true;
        if (edlChk) edlChk.checked = false;
      } else if (val === "digikam") {
        if (nfoChk) nfoChk.checked = false;
        if (xmpChk) xmpChk.checked = true;
        if (txtChk) txtChk.checked = true;
        if (jsonChk) jsonChk.checked = true;
        if (srtChk) srtChk.checked = true;
        if (edlChk) edlChk.checked = false;
      }
    });
  }

  // In-file tagging checkbox in Organizer tab syncs with config & settings
  const enableTaggingEl = document.getElementById("cfg-enable-tagging");
  const autoTagEl = document.getElementById("cfg-auto-tag");
  if (enableTaggingEl) {
    enableTaggingEl.addEventListener("change", async (e) => {
      if (autoTagEl) autoTagEl.checked = e.target.checked;
      await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enable_in_file_tagging: e.target.checked })
      });
    });
  }
  if (autoTagEl) {
    autoTagEl.addEventListener("change", async (e) => {
      if (enableTaggingEl) enableTaggingEl.checked = e.target.checked;
      await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enable_in_file_tagging: e.target.checked })
      });
    });
  }

  // Backup flush sync between Organizer tab and Settings tab
  const flushSuccessEl = document.getElementById("cfg-flush-backup-on-success");
  const flushQuickEl = document.getElementById("cfg-flush-backup-quick");
  if (flushSuccessEl) {
    flushSuccessEl.addEventListener("change", (e) => {
      if (flushQuickEl) flushQuickEl.checked = e.target.checked;
    });
  }
  if (flushQuickEl) {
    flushQuickEl.addEventListener("change", (e) => {
      if (flushSuccessEl) flushSuccessEl.checked = e.target.checked;
    });
  }

  // Purge / flush leftover .bak files
  const handleFlushBackups = async (statusElId) => {
    const statusEl = statusElId ? document.getElementById(statusElId) : null;
    if (statusEl) {
      statusEl.textContent = "Scanning for .bak files...";
      statusEl.style.color = "var(--text-muted)";
    }
    try {
      const res = await fetch("/api/storage/flush-backups", { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        const msg = data.flushed_count > 0
          ? `Flushed ${data.flushed_count} leftover .bak file(s)`
          : "No orphaned .bak files found (clean)";
        if (statusEl) {
          statusEl.textContent = msg;
          statusEl.style.color = "#34d399";
          setTimeout(() => { if (statusEl) statusEl.textContent = ""; }, 4000);
        }
        if (typeof showToast === "function") showToast(msg);
      } else {
        if (statusEl) {
          statusEl.textContent = "Flush failed";
          statusEl.style.color = "#f87171";
        }
      }
    } catch (err) {
      if (statusEl) {
        statusEl.textContent = "Error flushing backups";
        statusEl.style.color = "#f87171";
      }
    }
  };

  const btnFlushLog = document.getElementById("btn-flush-backups-log");
  if (btnFlushLog) btnFlushLog.addEventListener("click", () => handleFlushBackups(null));

  const btnFlushQuick = document.getElementById("btn-flush-backups-quick");
  if (btnFlushQuick) btnFlushQuick.addEventListener("click", () => handleFlushBackups("flush-backups-status-quick"));

  const btnFlushSettings = document.getElementById("btn-flush-backups");
  if (btnFlushSettings) btnFlushSettings.addEventListener("click", () => handleFlushBackups("flush-backups-status"));

  // Auto-rename sync between settings and batch header toggle
  const cfgAutoRename = document.getElementById("cfg-auto-rename");
  if (cfgAutoRename) {
    cfgAutoRename.addEventListener("change", (e) => {
      const quickToggle = document.getElementById("quick-auto-rename-toggle");
      const quickLabel = document.getElementById("quick-auto-rename-label");
      if (quickToggle) {
        quickToggle.checked = e.target.checked;
        if (quickLabel) {
          quickLabel.textContent = e.target.checked ? "ON" : "OFF";
          quickLabel.style.color = e.target.checked ? "#34d399" : "#94a3b8";
        }
      }
    });
  }

  // Settings Export & Import
  const btnExportConfig = document.getElementById("btn-export-config");
  if (btnExportConfig) {
    btnExportConfig.addEventListener("click", () => {
      window.location.href = "/api/config/export";
    });
  }

  const btnImportConfig = document.getElementById("btn-import-config");
  const fileImportConfig = document.getElementById("file-import-config");
  if (btnImportConfig && fileImportConfig) {
    btnImportConfig.addEventListener("click", () => {
      fileImportConfig.click();
    });

    fileImportConfig.addEventListener("change", async () => {
      if (!fileImportConfig.files || fileImportConfig.files.length === 0) return;
      const file = fileImportConfig.files[0];
      const formData = new FormData();
      formData.append("file", file);

      try {
        const res = await fetch("/api/config/import", {
          method: "POST",
          body: formData
        });
        const data = await res.json();
        if (res.ok && data.status === "ok") {
          alert("✅ Settings successfully imported!");
          await loadConfig();
          checkAIHealth();
          checkFFmpegStatus();
        } else {
          alert("❌ Failed to import settings: " + (data.detail || data.message || "Unknown error"));
        }
      } catch (err) {
        alert("❌ Error importing settings: " + err.message);
      } finally {
        fileImportConfig.value = "";
      }
    });
  }

  const btnDlLogsSettings = document.getElementById("btn-download-logs-settings");
  if (btnDlLogsSettings) {
    btnDlLogsSettings.addEventListener("click", () => {
      window.location.href = "/api/logs/download";
    });
  }
}


function toggleProviderSections(provider) {
  document.getElementById("section-ollama").classList.add("hidden");
  document.getElementById("section-openai").classList.add("hidden");
  document.getElementById("section-cloud").classList.add("hidden");

  if (provider === "ollama") {
    document.getElementById("section-ollama").classList.remove("hidden");
  } else if (provider === "openai_compatible") {
    document.getElementById("section-openai").classList.remove("hidden");
  } else if (provider === "cloud") {
    document.getElementById("section-cloud").classList.remove("hidden");
  }
}

async function checkAIHealth() {
  const badge = document.getElementById("ai-status-indicator");
  const hostEl = document.getElementById("summary-backend-host");
  const modelEl = document.getElementById("summary-backend-model");
  const stateEl = document.getElementById("summary-backend-state");
  const livePill = document.getElementById("backend-live-status-pill");

  try {
    const cfgRes = await fetch("/api/config");
    const cfg = await cfgRes.json();
    
    if (cfg.vision_provider === "ollama") {
      if (hostEl) hostEl.textContent = cfg.ollama_url || "http://localhost:11434";
      if (modelEl) modelEl.textContent = cfg.ollama_model || "llama3.2-vision";

      const res = await fetch("/api/models/ollama");
      const data = await res.json();
      if (data.connected) {
        if (badge) {
          badge.className = "status-badge connected";
          badge.textContent = `Ollama: Online (${cfg.ollama_model})`;
        }
        if (stateEl) {
          stateEl.className = "badge-tag processed";
          stateEl.textContent = "Online";
        }
        if (livePill) {
          livePill.className = "badge-tag processed";
          livePill.textContent = "✓ Ollama Connected";
        }
      } else {
        if (badge) {
          badge.className = "status-badge error";
          badge.textContent = "Ollama: Offline";
        }
        if (stateEl) {
          stateEl.className = "badge-tag danger";
          stateEl.textContent = "Offline (unreachable)";
        }
        if (livePill) {
          livePill.className = "badge-tag danger";
          livePill.textContent = "✗ Ollama Offline";
        }
      }
    } else if (cfg.vision_provider === "openai_compatible") {
      if (hostEl) hostEl.textContent = cfg.openai_compatible_url || "http://localhost:1234/v1";
      if (modelEl) modelEl.textContent = cfg.openai_compatible_model || "local-model";

      const res = await fetch("/api/models/openai");
      const data = await res.json();
      if (data.connected) {
        if (badge) {
          badge.className = "status-badge connected";
          badge.textContent = "LM Studio: Online";
        }
        if (stateEl) {
          stateEl.className = "badge-tag processed";
          stateEl.textContent = "Online";
        }
        if (livePill) {
          livePill.className = "badge-tag processed";
          livePill.textContent = "✓ LM Studio Connected";
        }
      } else {
        if (badge) {
          badge.className = "status-badge error";
          badge.textContent = "LM Studio: Offline";
        }
        if (stateEl) {
          stateEl.className = "badge-tag danger";
          stateEl.textContent = "Offline (unreachable)";
        }
        if (livePill) {
          livePill.className = "badge-tag danger";
          livePill.textContent = "✗ LM Studio Offline";
        }
      }
    } else {
      if (hostEl) hostEl.textContent = `Cloud (${cfg.cloud_provider})`;
      if (modelEl) modelEl.textContent = "Default Cloud Model";
      if (badge) {
        badge.className = "status-badge connected";
        badge.textContent = `Cloud: ${cfg.cloud_provider}`;
      }
      if (stateEl) {
        stateEl.className = "badge-tag processed";
        stateEl.textContent = "Configured";
      }
      if (livePill) {
        livePill.className = "badge-tag processed";
        livePill.textContent = `Cloud (${cfg.cloud_provider})`;
      }
    }
  } catch (e) {
    if (badge) {
      badge.className = "status-badge error";
      badge.textContent = "AI: Error";
    }
    if (stateEl) {
      stateEl.className = "badge-tag danger";
      stateEl.textContent = "Error";
    }
  }
}

let currentRenameFiles = [];

// --- Renaming & Organization ---
function initRenaming() {
  const btnPreview = document.getElementById("btn-refresh-rename-preview");
  const btnLoadCompleted = document.getElementById("btn-load-completed-renames");
  const btnExecute = document.getElementById("btn-execute-selected-renames");
  const btnUndo = document.getElementById("btn-undo-rename");
  const masterRename = document.getElementById("rename-master-select");
  const btnApplySchema = document.getElementById("btn-apply-schema-preview");
  const dateSourceSelect = document.getElementById("organizer-date-source");
  const dateOverrideBox = document.getElementById("organizer-date-override-box");
  const schemaPresetSelect = document.getElementById("organizer-schema-preset");
  const templateInput = document.getElementById("organizer-template-input");

  // Tab 1 controls for Batch Date
  const queueDateSrcEl = document.getElementById("queue-date-source");
  const queueDateOverrideBox = document.getElementById("queue-date-override-container");
  const btnGotoBatchRename = document.getElementById("btn-goto-batch-rename");

  if (queueDateSrcEl && queueDateOverrideBox) {
    queueDateSrcEl.addEventListener("change", () => {
      if (queueDateSrcEl.value === "override") {
        queueDateOverrideBox.classList.remove("hidden");
      } else {
        queueDateOverrideBox.classList.add("hidden");
      }
    });
  }

  if (btnGotoBatchRename) {
    btnGotoBatchRename.addEventListener("click", () => {
      // Switch tab to organizer
      const tabBtn = document.querySelector('[data-tab="tab-organizer"]');
      if (tabBtn) tabBtn.click();
      if (btnLoadCompleted) btnLoadCompleted.click();
    });
  }

  if (dateSourceSelect && dateOverrideBox) {
    dateSourceSelect.addEventListener("change", () => {
      if (dateSourceSelect.value === "override") {
        dateOverrideBox.classList.remove("hidden");
      } else {
        dateOverrideBox.classList.add("hidden");
      }
    });
  }

  if (schemaPresetSelect && templateInput) {
    schemaPresetSelect.addEventListener("change", () => {
      if (schemaPresetSelect.value !== "custom") {
        templateInput.value = schemaPresetSelect.value;
      }
      if (currentRenameFiles.length > 0) {
        fetchRenamePreview();
      }
    });
  }

  if (btnApplySchema) {
    btnApplySchema.addEventListener("click", () => {
      fetchRenamePreview();
    });
  }

  async function fetchRenamePreview() {
    if (!currentRenameFiles || currentRenameFiles.length === 0) {
      alert("No video clips selected. Click 'Load Completed Queue Clips' or 'Preview Scanned Folder Clips' first.");
      return;
    }

    const btnTarget = btnApplySchema || btnPreview;
    const oldText = btnTarget ? btnTarget.textContent : "";
    if (btnTarget) {
      btnTarget.disabled = true;
      btnTarget.textContent = "Updating...";
    }

    try {
      const dateSource = dateSourceSelect ? dateSourceSelect.value : "smart";
      let dateOverride = null;
      if (dateSource === "override") {
        const dVal = document.getElementById("organizer-date-override")?.value;
        const tVal = document.getElementById("organizer-time-override")?.value;
        if (dVal) {
          dateOverride = tVal ? `${dVal}T${tVal}` : dVal;
        }
      }

      const template = templateInput ? templateInput.value.trim() : "{date_compact}_{time_zulu}_{title}";

      const res = await fetch("/api/rename/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          file_paths: currentRenameFiles,
          date_source: dateSource,
          date_override: dateOverride,
          template: template
        })
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || res.statusText);
      }

      renamePreviews = await res.json();
      renderRenameTable();
    } catch (e) {
      alert("Failed to generate rename previews: " + e.message);
    } finally {
      if (btnTarget) {
        btnTarget.disabled = false;
        btnTarget.textContent = oldText;
      }
    }
  }

  if (btnLoadCompleted) {
    btnLoadCompleted.addEventListener("click", async () => {
      try {
        const res = await fetch("/api/queue/status");
        if (!res.ok) return;
        const data = await res.json();
        const completedTasks = (data.queue || []).filter(t => t.status === "completed" && t.file_path);
        if (completedTasks.length === 0) {
          alert("No completed queue tasks found in current session. Process clips first or click 'Preview Scanned Folder Clips'.");
          return;
        }
        currentRenameFiles = completedTasks.map(t => t.file_path);
        fetchRenamePreview();
      } catch (err) {
        alert("Failed to fetch completed tasks: " + err.message);
      }
    });
  }

  if (btnPreview) {
    btnPreview.addEventListener("click", () => {
      if (scannedVideos.length === 0) {
        alert("No scanned clips available. Scan a folder in Mode A first.");
        return;
      }
      currentRenameFiles = scannedVideos.map(v => v.path);
      fetchRenamePreview();
    });
  }

  if (masterRename) {
    masterRename.addEventListener("change", () => {
      document.querySelectorAll(".rename-item-chk").forEach(chk => {
        chk.checked = masterRename.checked;
      });
    });
  }

  if (btnExecute) {
    btnExecute.addEventListener("click", async () => {
      const selected = [];
      document.querySelectorAll(".rename-item-chk:checked").forEach(chk => {
        const row = chk.closest("tr");
        const inputEl = row ? row.querySelector(".rename-suggested-input") : null;
        const targetFilename = inputEl ? inputEl.value.trim() : chk.dataset.suggested;
        selected.push({
          original_path: chk.dataset.original,
          new_filename: targetFilename,
          new_creation_date: chk.dataset.dateUsed || null
        });
      });

      if (selected.length === 0) {
        alert("Please select at least one file to rename.");
        return;
      }

      if (!confirm(`Are you sure you want to rename ${selected.length} file(s)? Accompanying sidecars (.info.json, .srt, .txt, .xmp, .nfo) will also be safely renamed with updated dates.`)) {
        return;
      }

      btnExecute.disabled = true;
      btnExecute.textContent = "Renaming...";

      let successCount = 0;
      for (const item of selected) {
        try {
          const res = await fetch("/api/rename/execute", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(item)
          });
          if (res.ok) {
            const data = await res.json();
            if (data.status === "success" || data.status === "skipped") {
              successCount++;
              // Update paths in currentRenameFiles if changed
              if (data.renamed_to) {
                const idx = currentRenameFiles.indexOf(item.original_path);
                if (idx !== -1) currentRenameFiles[idx] = data.renamed_to;
              }
            }
          }
        } catch (e) {
          console.error("Rename failed for:", item, e);
        }
      }

      btnExecute.disabled = false;
      btnExecute.textContent = "✅ Apply Selected Renames";
      alert(`Successfully renamed ${successCount} file(s) and accompanying sidecars.`);

      // Refresh previews to show updated state
      fetchRenamePreview();
    });
  }

  if (btnUndo) {
    btnUndo.addEventListener("click", async () => {
      if (!confirm("Undo the most recent rename operation?")) return;
      try {
        const res = await fetch("/api/rename/undo", { method: "POST" });
        if (res.ok) {
          const data = await res.json();
          alert(`Undid rename:\nRestored: ${data.restored_to}`);
          fetchRenamePreview();
        } else {
          const err = await res.json();
          alert(`Undo failed: ${err.detail || "No transaction found"}`);
        }
      } catch (e) {
        alert("Undo error: " + e.message);
      }
    });
  }
}

function renderRenameTable() {
  const tbody = document.getElementById("rename-tbody");
  if (!tbody) return;
  if (!renamePreviews || renamePreviews.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty-state">No rename suggestions found. Load completed queue clips or scan a folder.</td></tr>`;
    return;
  }

  tbody.innerHTML = renamePreviews.map(item => {
    const isDiff = item.different;
    let badgeHtml = "";
    if (item.date_source_used === "filename") {
      badgeHtml = `<span class="badge" style="background:#0284c7; font-size:0.75rem; white-space:nowrap;" title="Extracted from video filename">📁 ${escapeHtml(item.date_used || '')} <small>(filename)</small></span>`;
    } else if (item.date_source_used === "override") {
      badgeHtml = `<span class="badge" style="background:#059669; font-size:0.75rem; white-space:nowrap;" title="Set by manual batch override">✏️ ${escapeHtml(item.date_used || '')} <small>(override)</small></span>`;
    } else if (item.date_source_used === "metadata") {
      badgeHtml = `<span class="badge" style="background:#475569; font-size:0.75rem; white-space:nowrap;" title="Read from container creation_time">⚙️ ${escapeHtml(item.date_used || '')} <small>(metadata)</small></span>`;
    } else {
      badgeHtml = `<span class="badge" style="background:#334155; font-size:0.75rem; white-space:nowrap;">${escapeHtml(item.date_used || '')}</span>`;
    }

    const hasOriginal = item.original_name && item.original_name !== item.current_name;

    return `
      <tr>
        <td><input type="checkbox" class="rename-item-chk" data-original="${escapeHtml(item.original_path)}" data-suggested="${escapeHtml(item.suggested_name)}" data-date-used="${escapeHtml(item.date_used || '')}" ${isDiff ? "checked" : ""}></td>
        <td><code>${escapeHtml(item.current_name)}</code></td>
        <td>
          <code>${escapeHtml(item.original_name || item.current_name)}</code>
          ${hasOriginal ? '<br><span style="font-size:0.7rem; color:#f59e0b; font-weight:600;">(Original File)</span>' : ''}
        </td>
        <td>${badgeHtml}</td>
        <td>
          <input type="text" class="rename-suggested-input" value="${escapeHtml(item.suggested_name)}" style="width:100%; min-width:240px; background:#0f172a; color:#38bdf8; font-weight:600; border:1px solid #334155; border-radius:4px; padding:0.3rem 0.5rem; font-size:0.85rem;" data-original="${escapeHtml(item.original_path)}">
        </td>
        <td>${isDiff ? '<span class="badge-tag unprocessed" style="white-space:nowrap;">Rename Ready</span>' : '<span class="badge-tag processed" style="white-space:nowrap;">Unchanged</span>'}</td>
      </tr>
    `;
  }).join("");
}


// --- Privacy & Storage ---
async function refreshStorageInfo() {
  try {
    const res = await fetch("/api/storage");
    if (!res.ok) return;
    const data = await res.json();

    document.getElementById("path-base-data").textContent = data.locations.base_data_dir;
    document.getElementById("path-cache").textContent = data.locations.cache_dir;
    const pathModels = document.getElementById("path-models");
    if (pathModels) pathModels.textContent = data.locations.models_dir;
    const pathUploads = document.getElementById("path-uploads");
    if (pathUploads) pathUploads.textContent = data.locations.uploads_dir;
    document.getElementById("path-history").textContent = data.locations.history_dir;
    document.getElementById("path-config").textContent = data.locations.config_file;

    document.getElementById("usage-cache-size").textContent = formatBytes(data.sizes_bytes.cache);
    const usageUploads = document.getElementById("usage-uploads-size");
    if (usageUploads) usageUploads.textContent = formatBytes(data.sizes_bytes.uploads || 0);
    const usageModels = document.getElementById("usage-models-size");
    if (usageModels) usageModels.textContent = formatBytes(data.sizes_bytes.models || 0);
    document.getElementById("usage-history-size").textContent = formatBytes(data.sizes_bytes.history);
    document.getElementById("usage-total-size").textContent = formatBytes(data.sizes_bytes.total);

    document.getElementById("usage-frames-count").textContent = data.counts.frames;
    document.getElementById("usage-audio-count").textContent = data.counts.audio_files;
    const countUploads = document.getElementById("usage-uploads-count");
    if (countUploads) countUploads.textContent = data.counts.uploads || 0;
  } catch (err) {
    console.error("Storage fetch failed:", err);
  }
}

function initPrivacy() {
  document.getElementById("btn-purge-cache").addEventListener("click", async () => {
    if (!confirm("Purge all extracted video frames and temporary audio files from cache?")) return;
    try {
      const res = await fetch("/api/storage/clear-cache", { method: "POST" });
      const data = await res.json();
      alert(`Cache purged! Freed ${data.freed_formatted}.`);
      refreshStorageInfo();
    } catch (e) {
      alert("Purge failed: " + e.message);
    }
  });

  const btnPurgeUploads = document.getElementById("btn-purge-uploads");
  if (btnPurgeUploads) {
    btnPurgeUploads.addEventListener("click", async () => {
      if (!confirm("Purge all uploaded videos in the staging directory?")) return;
      try {
        const res = await fetch("/api/storage/clear-uploads", { method: "POST" });
        const data = await res.json();
        alert(`Uploads purged! Freed ${data.freed_formatted}.`);
        refreshStorageInfo();
        pollUploads();
      } catch (e) {
        alert("Uploads purge failed: " + e.message);
      }
    });
  }

  document.getElementById("btn-purge-history").addEventListener("click", async () => {
    if (!confirm("Clear all activity logs and rename history records?")) return;
    try {
      const res = await fetch("/api/storage/clear-history", { method: "POST" });
      const data = await res.json();
      alert(`History purged! Freed ${data.freed_formatted}.`);
      refreshStorageInfo();
    } catch (e) {
      alert("History purge failed: " + e.message);
    }
  });

  document.getElementById("btn-factory-reset").addEventListener("click", async () => {
    if (!confirm("⚠️ FULL FACTORY RESET: This will wipe all cache, history, and reset settings to default.\n\nYour original video files will NEVER be touched.\n\nContinue?")) return;
    try {
      await fetch("/api/storage/reset", { method: "POST" });
      alert("Factory reset complete. Application restored to defaults.");
      location.reload();
    } catch (e) {
      alert("Reset error: " + e.message);
    }
  });
}


// --- Helpers ---
function formatBytes(bytes) {
  if (!bytes || bytes === 0) return "0 B";
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  let val = bytes;
  while (val >= 1024 && i < units.length - 1) {
    val /= 1024;
    i++;
  }
  return `${val.toFixed(1)} ${units[i]}`;
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// --- Results Modal Controller ---
function initResultsModal() {
  const modal = document.getElementById("modal-results");
  const btnClose = document.getElementById("btn-close-results-modal");
  const btnCloseBottom = document.getElementById("btn-close-results-modal-bottom");
  const btnCopyTags = document.getElementById("btn-copy-tags");

  const closeModal = () => {
    if (modal) modal.classList.add("hidden");
  };

  if (btnClose) btnClose.addEventListener("click", closeModal);
  if (btnCloseBottom) btnCloseBottom.addEventListener("click", closeModal);
  if (modal) {
    modal.addEventListener("click", (e) => {
      if (e.target === modal) closeModal();
    });
  }
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && modal && !modal.classList.contains("hidden")) {
      closeModal();
    }
  });

  if (btnCopyTags) {
    btnCopyTags.addEventListener("click", () => {
      const tagsInput = document.getElementById("results-display-tags");
      const tagsStr = tagsInput ? tagsInput.value.trim() : "";
      if (!tagsStr) return;

      navigator.clipboard.writeText(tagsStr).then(() => {
        const orig = btnCopyTags.textContent;
        btnCopyTags.textContent = "✅ Copied!";
        setTimeout(() => { btnCopyTags.textContent = orig; }, 2000);
      }).catch(() => {
        tagsInput.select();
        document.execCommand("copy");
        const orig = btnCopyTags.textContent;
        btnCopyTags.textContent = "✅ Copied!";
        setTimeout(() => { btnCopyTags.textContent = orig; }, 2000);
      });
    });
  }
}

async function openResultsModal(filePath) {
  const modal = document.getElementById("modal-results");
  if (!modal) return;

  try {
    const res = await fetch(`/api/results?file_path=${encodeURIComponent(filePath)}`);
    if (!res.ok) {
      let errDetail = `${res.status} ${res.statusText}`;
      try {
        const err = await res.json();
        errDetail = err.detail || errDetail;
      } catch (_) {
        try {
          const rawText = await res.text();
          if (rawText) errDetail = rawText;
        } catch (_) {}
      }
      alert(`Could not fetch analysis results: ${errDetail}`);
      return;
    }
    const data = await res.json();

    document.getElementById("results-modal-filename").textContent = data.filename;
    document.getElementById("results-display-title").textContent = data.title || data.filename;
    
    const suggestedEl = document.getElementById("results-suggested-name");
    const suggestedBox = document.getElementById("results-suggested-name-box");
    if (data.suggested_filename) {
      suggestedEl.textContent = data.suggested_filename;
      suggestedBox.classList.remove("hidden");
    } else {
      suggestedBox.classList.add("hidden");
    }

    document.getElementById("results-display-summary").textContent = data.summary || "No summary recorded.";

    // Key moments / events
    const eventsContainer = document.getElementById("results-display-events");
    eventsContainer.innerHTML = "";
    if (data.events && data.events.length > 0) {
      eventsContainer.innerHTML = data.events.map(ev => `
        <div class="results-event-row ${ev.is_highlight ? 'highlight' : ''}">
          <span class="results-event-time">${escapeHtml(ev.timecode || '')}</span>
          <span class="results-event-desc">${ev.is_highlight ? '★ ' : ''}${escapeHtml(ev.description || '')}</span>
        </div>
      `).join("");
    } else {
      eventsContainer.innerHTML = `<span class="text-muted" style="font-size:0.85rem;">No discrete timestamped events listed.</span>`;
    }

    // Tags
    const tagsInput = document.getElementById("results-display-tags");
    tagsInput.value = data.tags_string || (data.tags ? data.tags.join(", ") : "");

    const tagsPills = document.getElementById("results-tags-pills");
    tagsPills.innerHTML = "";
    if (data.tags && data.tags.length > 0) {
      tagsPills.innerHTML = data.tags.map(t => `<span class="tag-pill">${escapeHtml(t)}</span>`).join("");
    }

    // People
    const peopleGroup = document.getElementById("results-group-people");
    const peoplePills = document.getElementById("results-display-people");
    if (data.people && data.people.length > 0) {
      peopleGroup.classList.remove("hidden");
      peoplePills.innerHTML = data.people.map(p => `<span class="tag-pill" style="background:#1e3a5f; color:#93c5fd;">👤 ${escapeHtml(p)}</span>`).join("");
    } else {
      peopleGroup.classList.add("hidden");
    }

    // Animals & Pets
    const animalsGroup = document.getElementById("results-group-animals");
    const animalsPills = document.getElementById("results-display-animals");
    if (animalsGroup && animalsPills) {
      if (data.animals_or_pets && data.animals_or_pets.length > 0) {
        animalsGroup.classList.remove("hidden");
        animalsPills.innerHTML = data.animals_or_pets.map(a => `<span class="tag-pill" style="background:#14532d; color:#86efac;">🐕 ${escapeHtml(a)}</span>`).join("");
      } else {
        animalsGroup.classList.add("hidden");
      }
    }

    // Objects & Equipment (Interactive)
    currentModalVideoPath = filePath;
    currentModalObjects = (data.objects || []).slice();
    renderInteractiveObjects();

    // Transcript / Subtitles
    const transcriptGroup = document.getElementById("results-group-transcript");
    const transcriptBox = document.getElementById("results-display-transcript");
    const transcriptLabel = document.getElementById("results-transcript-label");
    const transcriptBadge = document.getElementById("results-transcript-badge");

    if (data.audio_transcript) {
      transcriptGroup.classList.remove("hidden");
      transcriptBox.textContent = `"${data.audio_transcript}"`;
      
      if (data.subtitles_used || data.subtitle_source === "external_srt") {
        if (transcriptLabel) transcriptLabel.textContent = "Dialogue Context (From .SRT Subtitles)";
        if (transcriptBadge) {
          transcriptBadge.textContent = "💬 .SRT Subtitle";
          transcriptBadge.className = "badge-tag processed";
        }
      } else if (data.subtitle_source === "embedded") {
        if (transcriptLabel) transcriptLabel.textContent = "Dialogue Context (From Embedded Subtitles)";
        if (transcriptBadge) {
          transcriptBadge.textContent = "💬 Embedded Track";
          transcriptBadge.className = "badge-tag processed";
        }
      } else {
        if (transcriptLabel) transcriptLabel.textContent = "Transcribed Speech / Dialogue";
        if (transcriptBadge) {
          transcriptBadge.textContent = "🎙️ Whisper AI";
          transcriptBadge.className = "badge-tag processed";
        }
      }
    } else {
      transcriptGroup.classList.add("hidden");
    }

    // Download buttons
    setupDownloadBtn("btn-download-nfo", data.sidecars?.nfo?.url);
    setupDownloadBtn("btn-download-xmp", data.sidecars?.xmp?.url);
    setupDownloadBtn("btn-download-txt", data.sidecars?.txt?.url);
    setupDownloadBtn("btn-download-json", data.sidecars?.json?.url);
    setupDownloadBtn("btn-download-srt", data.sidecars?.srt?.url);
    setupDownloadBtn("btn-download-edl", data.sidecars?.edl?.url);
    setupDownloadBtn("btn-download-video", data.video?.url);

    const btnDownloadOptions = document.getElementById("btn-download-video-options");
    if (btnDownloadOptions) {
      btnDownloadOptions.onclick = () => openDownloadModal(filePath, data.filename, data);
    }

    // Footer info
    const metaParts = [];
    if (data.provider) metaParts.push(`AI Provider: ${data.provider}`);
    if (data.model) metaParts.push(`Model: ${data.model}`);
    if (data.processed_at) metaParts.push(`Processed: ${new Date(data.processed_at).toLocaleString()}`);
    document.getElementById("results-meta-footer").textContent = metaParts.join(" • ");

    modal.classList.remove("hidden");
  } catch (err) {
    alert("Error loading analysis results: " + err.message);
  }
}

function setupDownloadBtn(elementId, url) {
  const el = document.getElementById(elementId);
  if (!el) return;
  if (url) {
    el.href = url;
    el.classList.remove("hidden");
    el.removeAttribute("disabled");
    el.style.opacity = "1";
    el.style.pointerEvents = "auto";
  } else {
    el.setAttribute("disabled", "true");
    el.classList.add("hidden");
    el.style.opacity = "0.35";
    el.style.pointerEvents = "none";
    el.href = "#";
  }
}

// --- People & Faces Gallery Controller ---
let allFaces = [];

function initFacesTab() {
  const btnRefresh = document.getElementById("btn-refresh-faces");
  if (btnRefresh) btnRefresh.addEventListener("click", loadFaces);

  const btnBackfillThumbs = document.getElementById("btn-backfill-face-thumbs");
  if (btnBackfillThumbs) {
    btnBackfillThumbs.addEventListener("click", async () => {
      btnBackfillThumbs.disabled = true;
      btnBackfillThumbs.textContent = "Scanning videos...";
      try {
        const res = await fetch("/api/faces/backfill-thumbnails", { method: "POST" });
        const data = await res.json();
        if (data.status === "ok") {
          if (data.backfilled_count > 0) {
            alert(`✅ Generated photos for ${data.backfilled_count} person(s) from processed videos!`);
          } else {
            alert("All recognized people already have pictures, or associated videos could not be accessed.");
          }
          loadFaces();
        } else {
          alert("Photo generation error: " + (data.detail || "Unknown error"));
        }
      } catch (err) {
        alert("Photo generation error: " + err.message);
      } finally {
        btnBackfillThumbs.disabled = false;
        btnBackfillThumbs.textContent = "📸 Fill Missing Photos";
      }
    });
  }

  const btnAutoGuess = document.getElementById("btn-auto-guess-faces");
  if (btnAutoGuess) {
    btnAutoGuess.addEventListener("click", async () => {
      btnAutoGuess.disabled = true;
      btnAutoGuess.textContent = "Analyzing descriptions...";
      try {
        const res = await fetch("/api/faces/auto-guess-names", { method: "POST" });
        const data = await res.json();
        if (data.status === "ok") {
          if (data.matches_count > 0) {
            const summary = data.matches.map(m => `• ${m.old_name} → ${m.new_name}`).join("\n");
            alert(`✅ Assigned names to ${data.matches_count} unnamed face(s):\n\n${summary}`);
          } else {
            alert("No unnamed faces could be matched from current video descriptions.");
          }
          loadFaces();
        } else {
          alert("Auto-name error: " + (data.detail || "Unknown error"));
        }
      } catch (err) {
        alert("Auto-name error: " + err.message);
      } finally {
        btnAutoGuess.disabled = false;
        btnAutoGuess.textContent = "🤖 Auto-Name from AI";
      }
    });
  }

  const btnExport = document.getElementById("btn-export-faces");
  if (btnExport) {
    btnExport.addEventListener("click", () => {
      window.location.href = "/api/faces/export";
    });
  }

  const btnImport = document.getElementById("btn-import-faces");
  const fileImport = document.getElementById("faces-import-file");
  if (btnImport && fileImport) {
    btnImport.addEventListener("click", () => {
      fileImport.click();
    });

    fileImport.addEventListener("change", async (e) => {
      const file = e.target.files[0];
      if (!file) return;

      if (!confirm(`Import face database from "${file.name}"? This will merge new records and face thumbnails with your current registry.`)) {
        fileImport.value = "";
        return;
      }

      const formData = new FormData();
      formData.append("file", file);

      btnImport.disabled = true;
      btnImport.textContent = "Importing...";

      try {
        const res = await fetch("/api/faces/import?merge=true", {
          method: "POST",
          body: formData
        });

        if (res.ok) {
          const data = await res.json();
          alert(`Database imported successfully! Added/updated ${data.imported_count} face identities.`);
          loadFaces();
        } else {
          const err = await res.json();
          alert(`Import failed: ${err.detail || "Unknown error"}`);
        }
      } catch (err) {
        alert("Import error: " + err.message);
      } finally {
        btnImport.disabled = false;
        btnImport.textContent = "📥 Import Database";
        fileImport.value = "";
      }
    });
  }

  const btnClearFaces = document.getElementById("btn-clear-faces");
  if (btnClearFaces) {
    btnClearFaces.addEventListener("click", async () => {
      if (!allFaces || allFaces.length === 0) {
        alert("The face database is already empty.");
        return;
      }
      const count = allFaces.length;
      if (!confirm(`Are you sure you want to clear all ${count} recognized people and face identities from the registry?\n\nThis will reset person clusters and delete cached face thumbnails. (Video files and sidecars will NOT be deleted).`)) {
        return;
      }
      try {
        const res = await fetch("/api/faces/clear", { method: "POST" });
        if (res.ok) {
          const data = await res.json();
          alert(`Face database cleared successfully (${data.cleared_count || count} identities removed).`);
          loadFaces();
        } else {
          const err = await res.json();
          alert(`Failed to clear database: ${err.detail || "Unknown error"}`);
        }
      } catch (err) {
        alert("Error clearing face database: " + err.message);
      }
    });
  }

  const triggerFaceReindex = async (btn) => {
    if (!btn) return;
    const origText = btn.textContent;
    btn.disabled = true;
    btn.textContent = "🔄 Re-indexing...";

    const quickDist = document.getElementById("faces-quick-distance")?.value;
    const cfgDist = document.getElementById("cfg-face-distance")?.value;
    const dist = parseFloat(quickDist || cfgDist || "0.45");

    const quickConf = document.getElementById("faces-quick-confidence")?.value;
    const cfgConf = document.getElementById("cfg-face-confidence")?.value;
    const conf = parseFloat(quickConf || cfgConf || "0.70");

    try {
      const res = await fetch("/api/faces/reindex", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ max_distance: dist, confidence: conf })
      });
      if (res.ok) {
        const data = await res.json();
        alert(`Re-indexing complete!\nMerged ${data.merged_count} duplicate identities.\nTotal unique identities: ${data.total_identities}.`);
        await loadConfig();
        await loadFaces();
        const btnPreview = document.getElementById("btn-refresh-rename-preview");
        if (btnPreview && typeof scannedVideos !== "undefined" && scannedVideos && scannedVideos.length > 0) {
          btnPreview.click();
        }
      } else {
        const err = await res.json();
        alert(`Failed to re-index faces: ${err.detail || "Unknown error"}`);
      }
    } catch (err) {
      alert("Error re-indexing faces: " + err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = origText;
    }
  };

  const btnReindex = document.getElementById("btn-reindex-faces");
  if (btnReindex) {
    btnReindex.addEventListener("click", () => triggerFaceReindex(btnReindex));
  }
  const btnReindexQuick = document.getElementById("btn-reindex-faces-quick");
  if (btnReindexQuick) {
    btnReindexQuick.addEventListener("click", () => triggerFaceReindex(btnReindexQuick));
  }
  const btnReindexOrganizer = document.getElementById("btn-reindex-faces-organizer");
  if (btnReindexOrganizer) {
    btnReindexOrganizer.addEventListener("click", () => triggerFaceReindex(btnReindexOrganizer));
  }

  // Quick sliders in People & Faces tab
  const quickConfEl = document.getElementById("faces-quick-confidence");
  const badgeQuickConfEl = document.getElementById("badge-faces-quick-confidence");
  if (quickConfEl) {
    quickConfEl.addEventListener("input", (e) => {
      const v = parseFloat(e.target.value).toFixed(2);
      if (badgeQuickConfEl) badgeQuickConfEl.textContent = v;
      const cfgFaceConf = document.getElementById("cfg-face-confidence");
      const badgeCfgConf = document.getElementById("badge-face-confidence");
      if (cfgFaceConf) cfgFaceConf.value = v;
      if (badgeCfgConf) badgeCfgConf.textContent = v;
      updateFaceSensitivityBadge(v);
    });
  }

  const quickDistEl = document.getElementById("faces-quick-distance");
  const badgeQuickDistEl = document.getElementById("badge-faces-quick-distance");
  if (quickDistEl) {
    quickDistEl.addEventListener("input", (e) => {
      const dist = parseFloat(e.target.value);
      const text = `Distance: ${dist.toFixed(2)} (Similarity: ${Math.max(0, 1 - dist).toFixed(2)})`;
      if (badgeQuickDistEl) badgeQuickDistEl.textContent = text;
      const cfgFaceDist = document.getElementById("cfg-face-distance");
      const badgeCfgDist = document.getElementById("badge-face-distance");
      if (cfgFaceDist) cfgFaceDist.value = dist;
      if (badgeCfgDist) badgeCfgDist.textContent = text;
    });
  }

  // Save Face Tuning button
  const btnSaveTuning = document.getElementById("btn-save-face-tuning");
  if (btnSaveTuning) {
    btnSaveTuning.addEventListener("click", async () => {
      const dist = parseFloat(document.getElementById("faces-quick-distance")?.value || "0.45");
      const conf = parseFloat(document.getElementById("faces-quick-confidence")?.value || "0.70");
      btnSaveTuning.disabled = true;
      btnSaveTuning.textContent = "Saving...";
      try {
        const res = await fetch("/api/config", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            face_detection_confidence: conf,
            face_max_distance: dist,
            face_match_threshold: 1.0 - dist
          })
        });
        if (res.ok) {
          alert(`Face recognition and clustering settings saved!\nDetection Confidence: ${conf.toFixed(2)}\nMax Distance: ${dist.toFixed(2)}`);
          await loadConfig();
        } else {
          const err = await res.json();
          alert(`Failed to save settings: ${err.detail || "Unknown error"}`);
        }
      } catch (err) {
        alert("Error saving settings: " + err.message);
      } finally {
        btnSaveTuning.disabled = false;
        btnSaveTuning.textContent = "💾 Save Values";
      }
    });
  }

  const searchInput = document.getElementById("faces-search-input");
  const btnClearSearch = document.getElementById("btn-clear-faces-search");
  if (searchInput) {
    searchInput.addEventListener("input", (e) => {
      const q = e.target.value.toLowerCase().trim();
      if (btnClearSearch) {
        if (q) btnClearSearch.classList.remove("hidden");
        else btnClearSearch.classList.add("hidden");
      }
      const filtered = allFaces.filter(f => f.name.toLowerCase().includes(q));
      renderFaces(filtered);
    });
  }
  if (btnClearSearch && searchInput) {
    btnClearSearch.addEventListener("click", () => {
      searchInput.value = "";
      btnClearSearch.classList.add("hidden");
      renderFaces(allFaces);
    });
  }
}

async function loadFaces() {
  const container = document.getElementById("faces-container");
  if (!container) return;

  try {
    // Keep config & face sliders fresh
    try {
      const cfgRes = await fetch("/api/config");
      if (cfgRes.ok) {
        const cfg = await cfgRes.json();
        currentAppConfig = cfg;
        const confVal = cfg.face_detection_confidence !== undefined ? cfg.face_detection_confidence : 0.70;
        const distVal = cfg.face_max_distance !== undefined ? cfg.face_max_distance : 0.45;
        const quickConfEl = document.getElementById("faces-quick-confidence");
        const badgeQuickConfEl = document.getElementById("badge-faces-quick-confidence");
        const quickDistEl = document.getElementById("faces-quick-distance");
        const badgeQuickDistEl = document.getElementById("badge-faces-quick-distance");
        if (quickConfEl) quickConfEl.value = confVal;
        if (badgeQuickConfEl) badgeQuickConfEl.textContent = Number(confVal).toFixed(2);
        if (quickDistEl) quickDistEl.value = distVal;
        if (badgeQuickDistEl) badgeQuickDistEl.textContent = `Distance: ${Number(distVal).toFixed(2)} (Similarity: ${(1 - Number(distVal)).toFixed(2)})`;
        updateFaceSensitivityBadge(confVal);
      }
    } catch (_) {}

    const res = await fetch("/api/faces");
    if (!res.ok) return;
    const data = await res.json();
    allFaces = data.faces || [];
    renderFaces(allFaces);
  } catch (err) {
    console.error("Failed to load faces:", err);
  }
}

function renderFaces(faces) {
  const container = document.getElementById("faces-container");
  if (!container) return;

  if (faces.length === 0) {
    container.innerHTML = `
      <div class="empty-state" style="grid-column: 1 / -1;">
        <span style="font-size:2.5rem; display:block; margin-bottom:0.5rem;">👤</span>
        <b>No recognized individuals yet.</b>
        <p class="text-muted" style="font-size:0.85rem; margin-top:6px; max-width:480px; margin-left:auto; margin-right:auto;">
          Enable Facial Recognition in <b>AI Connectors</b> Settings. When you process videos, recurring people will automatically appear here with face thumbnails and cluster IDs.
        </p>
      </div>
    `;
    return;
  }

  container.innerHTML = faces.map(face => {
    const isAutoNamed = face.name.startsWith("Person_");
    const thumbSrc = face.thumbnail_url || "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='100' height='100' fill='%2364748b'><rect width='100' height='100' fill='%231e293b'/><text x='50%' y='55%' dominant-baseline='middle' text-anchor='middle' font-size='30'>👤</text></svg>";

    return `
      <div class="face-card" data-id="${escapeHtml(face.id)}">
        <div class="face-thumb-wrap">
          <img src="${thumbSrc}" class="face-thumb-img" alt="${escapeHtml(face.name)}" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'100\\' height=\\'100\\' fill=\\'%2364748b\\'><rect width=\\'100\\' height=\\'100\\' fill=\\'%231e293b\\'/><text x=\\'50%\\' y=\\'55%\\' dominant-baseline=\\'middle\\' text-anchor=\\'middle\\' font-size=\\'30\\'>👤</text></svg>'">
          ${isAutoNamed ? `<span class="face-badge-auto">Auto</span>` : ''}
        </div>
        <input type="text" class="face-name-input" id="input-name-${face.id}" value="${escapeHtml(face.name)}" placeholder="Enter name...">
        <div class="face-meta-info">
          <span>Seen in <b>${face.video_count}</b> video(s)</span>
        </div>
        <div class="face-card-actions">
          <button class="btn btn-sm btn-primary" onclick="saveFaceName('${face.id}')">💾 Save Name</button>
          <button class="btn btn-sm btn-danger-outline" onclick="deleteFace('${face.id}')" title="Delete face identity">🗑️</button>
        </div>
      </div>
    `;
  }).join("");
}

async function saveFaceName(personId) {
  const input = document.getElementById(`input-name-${personId}`);
  if (!input) return;
  const newName = input.value.trim();
  if (!newName) {
    alert("Please enter a valid name.");
    return;
  }

  try {
    const res = await fetch(`/api/faces/${encodeURIComponent(personId)}/rename`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ new_name: newName, update_sidecars: true })
    });
    if (res.ok) {
      const data = await res.json();
      alert(`Updated to "${newName}"! Updated ${data.updated_sidecars_count} video sidecars.`);
      loadFaces();
    } else {
      const err = await res.json();
      alert(`Rename failed: ${err.detail || "Unknown error"}`);
    }
  } catch (err) {
    alert("Rename error: " + err.message);
  }
}

async function deleteFace(personId) {
  if (!confirm("Remove this face identity from the registry?")) return;
  try {
    const res = await fetch(`/api/faces/${encodeURIComponent(personId)}`, { method: "DELETE" });
    if (res.ok) {
      loadFaces();
    }
  } catch (err) {
    alert("Delete error: " + err.message);
  }
}

function toggleFaceProviderSections(provider) {
  const compSec = document.getElementById("section-compreface");
  const builtinSec = document.getElementById("section-builtin-face");
  if (compSec) {
    if (provider === "compreface") {
      compSec.classList.remove("hidden");
    } else {
      compSec.classList.add("hidden");
    }
  }
  if (builtinSec) {
    if (provider === "builtin") {
      builtinSec.classList.remove("hidden");
    } else {
      builtinSec.classList.add("hidden");
    }
  }
}

function toggleWhisperBackendSections(backend) {
  const remoteSec = document.getElementById("section-whisper-remote");
  const localSec = document.getElementById("section-whisper-local");
  if (remoteSec) {
    if (backend === "remote") {
      remoteSec.classList.remove("hidden");
    } else {
      remoteSec.classList.add("hidden");
    }
  }
  if (localSec) {
    if (backend === "remote") {
      localSec.classList.add("hidden");
    } else {
      localSec.classList.remove("hidden");
    }
  }
}

function updateFaceSensitivityBadge(val) {
  const badge = document.getElementById("faces-sensitivity-badge");
  if (!badge) return;
  const num = parseFloat(val);
  let label = "Strict";
  if (num >= 0.85) label = "Ultra-Strict";
  else if (num >= 0.70) label = "Strict (Recommended)";
  else if (num >= 0.55) label = "Moderate";
  else label = "Sensitive";
  badge.textContent = `🎯 Strictness: ${num.toFixed(2)} (${label}) ⚙️`;
}

// --- Long Video Sampling Strategy UI helper ---
function toggleSamplingStrategyFields(strategy) {
  const grpInterval = document.getElementById("grp-sampling-interval");
  if (grpInterval) {
    if (strategy === "interval") {
      grpInterval.classList.remove("hidden");
    } else {
      grpInterval.classList.add("hidden");
    }
  }
}

// --- Interactive Object Tagging ---
let currentModalVideoPath = "";
let currentModalObjects = [];

function renderInteractiveObjects() {
  const objectsPills = document.getElementById("results-display-objects");
  const objectsGroup = document.getElementById("results-group-objects");
  if (!objectsPills) return;
  if (objectsGroup) objectsGroup.classList.remove("hidden");

  if (!currentModalObjects || currentModalObjects.length === 0) {
    objectsPills.innerHTML = `<span class="text-muted" style="font-size:0.8rem;">No object tags recorded. Type an object above to tag.</span>`;
    return;
  }
  objectsPills.innerHTML = currentModalObjects.map((obj, idx) => `
    <span class="object-tag-pill">
      🎾 ${escapeHtml(obj)}
      <button type="button" class="btn-remove-obj" title="Remove object tag" onclick="removeObjectTag(${idx})">&times;</button>
    </span>
  `).join("");
}

async function removeObjectTag(index) {
  if (!currentModalObjects || index < 0 || index >= currentModalObjects.length) return;
  currentModalObjects.splice(index, 1);
  renderInteractiveObjects();
  await saveModalObjects();
}

async function addObjectTag() {
  const input = document.getElementById("input-new-object-tag");
  if (!input) return;
  const val = input.value.trim();
  if (!val) return;
  if (!currentModalObjects) currentModalObjects = [];
  if (!currentModalObjects.some(o => o.toLowerCase() === val.toLowerCase())) {
    currentModalObjects.push(val);
    renderInteractiveObjects();
    input.value = "";
    await saveModalObjects();
  }
}

async function saveModalObjects() {
  if (!currentModalVideoPath) return;
  try {
    const res = await fetch("/api/results/update-objects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        file_path: currentModalVideoPath,
        objects: currentModalObjects
      })
    });
    if (!res.ok) {
      console.warn("Failed to persist object tags");
    }
  } catch (err) {
    console.error("Error saving object tags:", err);
  }
}

// --- Video Download Options Modal ---
let currentDownloadVideoPath = "";
let currentDownloadVideoName = "";
let currentDownloadIsMkv = false;

async function openDownloadModal(filePath, filename, optionalData = null) {
  currentDownloadVideoPath = filePath;
  currentDownloadVideoName = filename;
  const modal = document.getElementById("modal-download-video");
  if (!modal) return;

  const dotIdx = filename.lastIndexOf(".");
  const ext = dotIdx !== -1 ? filename.substring(dotIdx) : ".mp4";
  const stem = dotIdx !== -1 ? filename.substring(0, dotIdx) : filename;
  const isMkv = ext.toLowerCase() === ".mkv";
  currentDownloadIsMkv = isMkv;

  const origLbl = document.getElementById("dl-lbl-orig-name");
  if (origLbl) origLbl.textContent = filename;

  const aiBadgeTitle = document.getElementById("dl-ai-detected-title");
  if (aiBadgeTitle) aiBadgeTitle.textContent = "Loading AI analysis...";

  // Check or fetch results for AI title, slug, and date
  let data = optionalData;
  if (!data || !data.title) {
    try {
      const res = await fetch(`/api/results?file_path=${encodeURIComponent(filePath)}`);
      if (res.ok) {
        data = await res.json();
      }
    } catch (e) {
      console.warn("Could not fetch results for download modal:", e);
    }
  }

  // Determine metadata values
  const rawTitle = (data && data.title) ? data.title : stem;
  const cleanTitle = rawTitle.replace(/[^a-zA-Z0-9_\- ]/g, "").replace(/\s+/g, "_") || stem;
  const rawSlug = (data && data.ai_slug) ? data.ai_slug : ((data && data.suggested_filename) ? data.suggested_filename : cleanTitle.toLowerCase());
  const cleanSlug = rawSlug.replace(/[^a-zA-Z0-9_\- ]/g, "").replace(/\s+/g, "_").toLowerCase() || stem.toLowerCase();

  let dateStr = new Date().toISOString().slice(0, 10);
  if (data && data.creation_time) {
    try {
      dateStr = new Date(data.creation_time).toISOString().slice(0, 10);
    } catch (_) {}
  }

  if (aiBadgeTitle) {
    aiBadgeTitle.textContent = rawTitle;
  }

  // Compute naming options
  const configuredCandidate = (data && data.suggested_filename) ? data.suggested_filename : `${dateStr}_${cleanTitle}${ext}`;
  const dateAiCandidate = `${dateStr}_${cleanTitle}${ext}`;
  const aiOnlyCandidate = `${cleanTitle}${ext}`;
  const aiSlugCandidate = `${cleanSlug}${ext}`;

  const lblConfigured = document.getElementById("dl-lbl-configured-name");
  if (lblConfigured) lblConfigured.textContent = configuredCandidate;

  const lblDateAi = document.getElementById("dl-lbl-date-ai-name");
  if (lblDateAi) lblDateAi.textContent = dateAiCandidate;

  const lblAiOnly = document.getElementById("dl-lbl-ai-only-name");
  if (lblAiOnly) lblAiOnly.textContent = aiOnlyCandidate;

  const lblAiSlug = document.getElementById("dl-lbl-ai-slug-name");
  if (lblAiSlug) lblAiSlug.textContent = aiSlugCandidate;

  const inputCustom = document.getElementById("dl-input-custom-name");
  if (inputCustom) {
    inputCustom.value = configuredCandidate;
    inputCustom.classList.add("hidden");
  }

  // Pre-select configured scheme by default
  const radioConfigured = document.getElementById("dl-name-configured");
  const radioDateAi = document.getElementById("dl-name-date-ai");
  const radioAiOnly = document.getElementById("dl-name-ai-only");
  const radioAiSlug = document.getElementById("dl-name-ai-slug");
  const radioOrig = document.getElementById("dl-name-original");

  if (radioConfigured) {
    radioConfigured.checked = true;
  } else if (radioDateAi) {
    radioDateAi.checked = true;
  }

  // Radio change listener to toggle custom input
  document.querySelectorAll('input[name="dl-filename-choice"]').forEach(radio => {
    radio.onchange = () => {
      if (inputCustom) {
        if (radio.value === "custom") {
          inputCustom.classList.remove("hidden");
          inputCustom.focus();
        } else {
          inputCustom.classList.add("hidden");
        }
      }
    };
  });

  // Subtitle note
  const subNote = document.getElementById("dl-subtitles-note");
  const subChk = document.getElementById("dl-chk-embed-subtitles");
  if (subChk) subChk.checked = true;

  if (subNote) {
    if (isMkv) {
      subNote.innerHTML = `✅ <b>Native MKV Container</b>: Soft subtitles will be losslessly embedded as a selectable track using stream copy (zero re-encoding).`;
      subNote.style.color = "#34d399";
    } else {
      subNote.innerHTML = `⚠️ <b>Container is ${ext.toUpperCase()}</b>: Per media standards, soft subtitles are not embedded in MP4/MOV to prevent player incompatibility. If soft subtitles are enabled, the file will be downloaded as a standard video, or losslessly exported to <b>MKV</b> if you enter a .mkv filename.`;
      subNote.style.color = "#93c5fd";
    }
  }

  modal.classList.remove("hidden");
}

function closeDownloadModal() {
  const modal = document.getElementById("modal-download-video");
  if (modal) modal.classList.add("hidden");
}

async function executeCustomDownload() {
  if (!currentDownloadVideoPath) return;

  const btnConfirm = document.getElementById("btn-confirm-download-video");
  const originalText = btnConfirm ? btnConfirm.textContent : "⬇️ Download Video";
  if (btnConfirm) {
    btnConfirm.textContent = "⏳ Preparing...";
    btnConfirm.disabled = true;
  }

  try {
    let chosenName = currentDownloadVideoName;
    const nameChoice = document.querySelector('input[name="dl-filename-choice"]:checked')?.value;
    if (nameChoice === "configured") {
      chosenName = document.getElementById("dl-lbl-configured-name")?.textContent || currentDownloadVideoName;
    } else if (nameChoice === "date_ai") {
      chosenName = document.getElementById("dl-lbl-date-ai-name")?.textContent || currentDownloadVideoName;
    } else if (nameChoice === "ai_only") {
      chosenName = document.getElementById("dl-lbl-ai-only-name")?.textContent || currentDownloadVideoName;
    } else if (nameChoice === "ai_slug") {
      chosenName = document.getElementById("dl-lbl-ai-slug-name")?.textContent || currentDownloadVideoName;
    } else if (nameChoice === "custom") {
      chosenName = document.getElementById("dl-input-custom-name")?.value.trim() || currentDownloadVideoName;
    } else {
      chosenName = currentDownloadVideoName;
    }

    const embedTags = document.getElementById("dl-chk-embed-tags")?.checked ?? true;
    const embedSubtitles = document.getElementById("dl-chk-embed-subtitles")?.checked ?? true;
    
    // Determine target format
    let targetFormat = "original";
    if (currentDownloadIsMkv || chosenName.toLowerCase().endsWith(".mkv")) {
      targetFormat = "mkv";
    }

    const payload = {
      file_path: currentDownloadVideoPath,
      output_filename: chosenName,
      embed_tags: embedTags,
      embed_subtitles: embedSubtitles,
      target_format: targetFormat
    };

    const res = await fetch("/api/download/custom-video", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || res.statusText);
    }

    const blob = await res.blob();
    const blobUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = blobUrl;
    a.download = chosenName;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(blobUrl);

    closeDownloadModal();
  } catch (err) {
    alert("Download failed: " + err.message);
  } finally {
    if (btnConfirm) {
      btnConfirm.textContent = originalText;
      btnConfirm.disabled = false;
    }
  }
}

// --- Host Filesystem Browser Modal ---
let fsCurrentPath = "";
let fsParentPath = null;
let fsBrowserMode = "folder"; // "folder" | "files"
let fsSelectedFiles = new Set();
let fsCachedFolders = [];
let fsCachedFiles = [];

function initFsBrowser() {
  const modal = document.getElementById("modal-fs-browser");
  const btnClose = document.getElementById("btn-close-fs-modal");
  const btnCancel = document.getElementById("btn-fs-cancel");
  const btnConfirm = document.getElementById("btn-fs-confirm");
  const btnUp = document.getElementById("btn-fs-up");
  const btnRefresh = document.getElementById("btn-fs-refresh");
  const filterInput = document.getElementById("fs-filter-input");
  const btnSelectAll = document.getElementById("btn-fs-select-all");
  const btnDeselectAll = document.getElementById("btn-fs-deselect-all");

  const btnBrowseFolder = document.getElementById("btn-browse-folder");
  if (btnBrowseFolder) {
    btnBrowseFolder.addEventListener("click", async () => {
      btnBrowseFolder.disabled = true;
      const origText = btnBrowseFolder.textContent;
      btnBrowseFolder.textContent = "Opening...";

      try {
        const curPath = document.getElementById("scan-folder-path")?.value.trim() || null;
        const res = await fetch("/api/fs/pick-native", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ target: "folder", initial_dir: curPath })
        });
        if (res.ok) {
          const data = await res.json();
          if (data.status === "selected" && data.path) {
            document.getElementById("scan-folder-path").value = data.path;
            const btnScan = document.getElementById("btn-scan");
            if (btnScan) btnScan.click();
            return;
          } else if (data.status === "cancelled") {
            // User deliberately closed or cancelled native dialog
            return;
          }
        }
      } catch (e) {
        console.warn("Native folder dialog:", e);
      } finally {
        btnBrowseFolder.disabled = false;
        btnBrowseFolder.textContent = origText;
      }

      // If native dialog is unsupported, fallback to web modal
      openFsBrowser("folder");
    });
  }

  const btnBrowseFiles = document.getElementById("btn-browse-files");
  if (btnBrowseFiles) {
    btnBrowseFiles.addEventListener("click", async () => {
      btnBrowseFiles.disabled = true;
      const origText = btnBrowseFiles.textContent;
      btnBrowseFiles.textContent = "Opening...";

      try {
        const curPath = document.getElementById("scan-folder-path")?.value.trim() || null;
        const res = await fetch("/api/fs/pick-native", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ target: "files", initial_dir: curPath })
        });
        if (res.ok) {
          const data = await res.json();
          if (data.status === "selected" && data.paths && data.paths.length > 0) {
            await requestEnqueueWithConflictCheck(data.paths, false);
            return;
          } else if (data.status === "cancelled") {
            // User deliberately closed or cancelled native dialog
            return;
          }
        }
      } catch (e) {
        console.warn("Native files dialog:", e);
      } finally {
        btnBrowseFiles.disabled = false;
        btnBrowseFiles.textContent = origText;
      }

      // If native dialog is unsupported, fallback to web modal
      openFsBrowser("files");
    });
  }

  const btnFsNative = document.getElementById("btn-fs-native");
  if (btnFsNative) {
    btnFsNative.addEventListener("click", async () => {
      btnFsNative.disabled = true;
      const origText = btnFsNative.textContent;
      btnFsNative.textContent = "Opening...";
      try {
        const res = await fetch("/api/fs/pick-native", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ target: fsBrowserMode, initial_dir: fsCurrentPath || null })
        });
        if (res.ok) {
          const data = await res.json();
          if (data.status === "selected") {
            if (fsBrowserMode === "folder" && data.path) {
              const folderInput = document.getElementById("scan-folder-path");
              if (folderInput) folderInput.value = data.path;
              closeFsBrowser();
              const btnScan = document.getElementById("btn-scan");
              if (btnScan) btnScan.click();
              return;
            } else if (fsBrowserMode === "files" && data.paths && data.paths.length > 0) {
              closeFsBrowser();
              await requestEnqueueWithConflictCheck(data.paths, false);
              return;
            }
          }
        }
      } catch (e) {
        console.warn("Native dialog invocation:", e);
      } finally {
        btnFsNative.disabled = false;
        btnFsNative.textContent = origText;
      }
    });
  }

  if (btnClose) btnClose.addEventListener("click", closeFsBrowser);
  if (btnCancel) btnCancel.addEventListener("click", closeFsBrowser);

  if (btnUp) {
    btnUp.addEventListener("click", () => {
      if (fsParentPath) loadFsPath(fsParentPath);
    });
  }

  if (btnRefresh) {
    btnRefresh.addEventListener("click", () => {
      loadFsPath(fsCurrentPath);
    });
  }

  if (filterInput) {
    filterInput.addEventListener("input", () => {
      renderFsItems(filterInput.value.toLowerCase().trim());
    });
  }

  if (btnSelectAll) {
    btnSelectAll.addEventListener("click", () => {
      fsCachedFiles.forEach(f => fsSelectedFiles.add(f.path));
      renderFsItems(filterInput ? filterInput.value.toLowerCase().trim() : "");
      updateFsSelectionSummary();
    });
  }

  if (btnDeselectAll) {
    btnDeselectAll.addEventListener("click", () => {
      fsSelectedFiles.clear();
      renderFsItems(filterInput ? filterInput.value.toLowerCase().trim() : "");
      updateFsSelectionSummary();
    });
  }

  if (btnConfirm) {
    btnConfirm.addEventListener("click", async () => {
      if (fsBrowserMode === "folder") {
        if (!fsCurrentPath) return;
        const folderInput = document.getElementById("scan-folder-path");
        if (folderInput) folderInput.value = fsCurrentPath;
        closeFsBrowser();
        // Automatically trigger scan
        const btnScan = document.getElementById("btn-scan");
        if (btnScan) btnScan.click();
      } else {
        // Files mode: collect selected files
        const selected = Array.from(fsSelectedFiles);
        if (selected.length === 0) {
          alert("Please select at least one video file.");
          return;
        }
        closeFsBrowser();
        await requestEnqueueWithConflictCheck(selected, false);
      }
    });
  }
}

async function openFsBrowser(mode = "folder") {
  fsBrowserMode = mode;
  fsSelectedFiles.clear();
  const modal = document.getElementById("modal-fs-browser");
  const titleEl = document.getElementById("fs-modal-title");
  const subEl = document.getElementById("fs-modal-subtitle");
  const confirmBtn = document.getElementById("btn-fs-confirm");
  const multiCtrl = document.getElementById("fs-multi-select-controls");

  if (mode === "folder") {
    titleEl.textContent = "📁 Select Footage Folder on Host";
    subEl.textContent = "Navigate host directories and choose a folder to batch scan";
    confirmBtn.textContent = "Select This Folder";
    confirmBtn.className = "btn btn-primary";
    if (multiCtrl) multiCtrl.classList.add("hidden");
  } else {
    titleEl.textContent = "🎬 Select Video Files on Host";
    subEl.textContent = "Navigate and check specific video files to add to the processing queue";
    confirmBtn.textContent = "Add Selected Files to Queue";
    confirmBtn.className = "btn btn-success";
    if (multiCtrl) multiCtrl.classList.remove("hidden");
  }

  modal.classList.remove("hidden");
  // Default to existing path if set, or Home
  const existingPath = document.getElementById("scan-folder-path")?.value.trim();
  await loadFsPath(existingPath || "");
}

function closeFsBrowser() {
  const modal = document.getElementById("modal-fs-browser");
  if (modal) modal.classList.add("hidden");
  fsSelectedFiles.clear();
}

async function loadFsPath(targetPath) {
  const viewEl = document.getElementById("fs-list-view");
  const countEl = document.getElementById("fs-listing-count");
  if (viewEl) viewEl.innerHTML = `<div class="empty-state">Loading directory contents...</div>`;
  if (countEl) countEl.textContent = "Loading...";

  try {
    const url = targetPath ? `/api/fs/browse?path=${encodeURIComponent(targetPath)}` : `/api/fs/browse`;
    const res = await fetch(url);
    if (!res.ok) {
      const err = await res.json();
      alert(`Cannot open folder: ${err.detail || "Access error"}`);
      return;
    }
    const data = await res.json();
    fsCurrentPath = data.current_path;
    fsParentPath = data.parent_path;
    fsCachedFolders = data.folders || [];
    fsCachedFiles = data.files || [];

    // Render Shortcuts
    renderFsShortcuts(data.quick_locations || []);
    // Render Breadcrumbs
    renderFsBreadcrumbs(fsCurrentPath);
    // Render Items
    const filterInput = document.getElementById("fs-filter-input");
    if (filterInput) filterInput.value = "";
    renderFsItems("");
    updateFsSelectionSummary();

    // Disable Up button if at root
    const btnUp = document.getElementById("btn-fs-up");
    if (btnUp) btnUp.disabled = !fsParentPath;

  } catch (e) {
    if (viewEl) viewEl.innerHTML = `<div class="empty-state error-text">Error loading folder: ${escapeHtml(e.message)}</div>`;
  }
}

function renderFsShortcuts(shortcuts) {
  const bar = document.getElementById("fs-shortcuts-bar");
  if (!bar) return;
  bar.innerHTML = shortcuts.map(s => `
    <button class="fs-shortcut-btn" onclick="loadFsPath('${escapeHtml(s.path).replace(/'/g, "\\'")}')">
      ${escapeHtml(s.name)}
    </button>
  `).join("");
}

function renderFsBreadcrumbs(fullPath) {
  const container = document.getElementById("fs-breadcrumbs");
  if (!container) return;

  const isWin = fullPath.includes(":\\") || fullPath.includes(":/");
  const sep = isWin ? "\\" : "/";
  const parts = fullPath.split(/[\\/]/).filter(Boolean);

  let html = "";
  if (!isWin) {
    html += `<span class="fs-crumb" onclick="loadFsPath('/')">/</span>`;
  }

  let accumulated = "";
  parts.forEach((p, idx) => {
    if (isWin && idx === 0) {
      accumulated = p + "\\";
    } else {
      accumulated = accumulated ? `${accumulated}${sep}${p}` : (isWin ? `${p}\\` : `/${p}`);
    }
    const safePath = escapeHtml(accumulated).replace(/'/g, "\\'");
    html += `<span class="fs-crumb-sep">${sep}</span>`;
    html += `<span class="fs-crumb" onclick="loadFsPath('${safePath}')">${escapeHtml(p)}</span>`;
  });

  container.innerHTML = html;
}

function renderFsItems(filterText) {
  const viewEl = document.getElementById("fs-list-view");
  const countEl = document.getElementById("fs-listing-count");
  if (!viewEl) return;

  const filteredFolders = fsCachedFolders.filter(f => !filterText || f.name.toLowerCase().includes(filterText));
  const filteredFiles = fsCachedFiles.filter(f => !filterText || f.name.toLowerCase().includes(filterText));

  if (countEl) {
    countEl.textContent = `${filteredFolders.length} folder(s), ${filteredFiles.length} video(s)`;
  }

  if (filteredFolders.length === 0 && filteredFiles.length === 0) {
    viewEl.innerHTML = `<div class="empty-state">No matching folders or video files in this directory.</div>`;
    return;
  }

  let html = "";

  // Render Folders
  filteredFolders.forEach(folder => {
    const safePath = escapeHtml(folder.path).replace(/'/g, "\\'");
    html += `
      <div class="fs-item" onclick="loadFsPath('${safePath}')" title="Open folder ${escapeHtml(folder.name)}">
        <div class="fs-item-name">
          <span class="fs-item-icon">📁</span>
          <b>${escapeHtml(folder.name)}</b>
        </div>
        <span class="fs-item-meta">Folder</span>
      </div>
    `;
  });

  // Render Video Files
  filteredFiles.forEach(file => {
    const isChecked = fsSelectedFiles.has(file.path);
    const safePath = escapeHtml(file.path).replace(/'/g, "\\'");

    if (fsBrowserMode === "files") {
      html += `
        <div class="fs-item ${isChecked ? "selected" : ""}" onclick="toggleFsFileSelection('${safePath}')">
          <div class="fs-item-name">
            <input type="checkbox" class="fs-file-chk" ${isChecked ? "checked" : ""} onclick="event.stopPropagation(); toggleFsFileSelection('${safePath}');">
            <span class="fs-item-icon">🎬</span>
            <span>${escapeHtml(file.name)}</span>
          </div>
          <span class="fs-item-meta">${escapeHtml(file.size_formatted)}</span>
        </div>
      `;
    } else {
      // In folder mode, show videos as preview list
      html += `
        <div class="fs-item" style="opacity: 0.85; cursor: default;">
          <div class="fs-item-name">
            <span class="fs-item-icon">🎬</span>
            <span>${escapeHtml(file.name)}</span>
          </div>
          <span class="fs-item-meta">${escapeHtml(file.size_formatted)}</span>
        </div>
      `;
    }
  });

  viewEl.innerHTML = html;
}

function toggleFsFileSelection(filePath) {
  if (fsSelectedFiles.has(filePath)) {
    fsSelectedFiles.delete(filePath);
  } else {
    fsSelectedFiles.add(filePath);
  }
  const filterInput = document.getElementById("fs-filter-input");
  renderFsItems(filterInput ? filterInput.value.toLowerCase().trim() : "");
  updateFsSelectionSummary();
}

function updateFsSelectionSummary() {
  const summaryEl = document.getElementById("fs-selected-summary");
  if (!summaryEl) return;
  if (fsBrowserMode === "folder") {
    summaryEl.textContent = `Current Folder: ${fsCurrentPath}`;
  } else {
    summaryEl.textContent = `${fsSelectedFiles.size} of ${fsCachedFiles.length} video(s) selected`;
  }
}

