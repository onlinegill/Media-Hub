function scheduleMediaOptions(schedule) {
  const playlists = state.playlists.map(p => `<option value="playlist|${esc(p.id)}" ${schedule.playlist_id === p.id ? "selected" : ""}>Playlist: ${esc(p.name)} (${p.tracks.length} songs)</option>`).join("");
  return `<option value="" ${!schedule.path && !schedule.playlist_id ? "selected" : ""}>Choose a file or playlist</option><optgroup label="Playlists">${playlists}</optgroup><optgroup label="Audio files">${mediaOptions(schedule.playlist_id ? "" : schedule.source, schedule.playlist_id ? "" : schedule.path)}</optgroup>`;
}

function renderPlaylists() {
  $("#playlistGrid").innerHTML = state.playlists.length ? state.playlists.map(p => {
    const active = state.queues.find(q => q.playlist_id === p.id);
    return `<div class="schedule-card"><div class="schedule-name">${esc(p.name)}</div><div class="small">${p.tracks.length} songs · ${p.repeat ? "Repeat" : "Play once"}</div>${active ? `<div class="small">Song ${active.track} of ${active.total} · ${esc(state.outputs.find(o => o.entity_id === active.entity_id)?.name || active.entity_id)}</div>` : ""}<div class="schedule-actions"><button class="btn primary" data-pplay="${p.id}">▶ Play</button><button class="btn" data-pedit="${p.id}">Edit</button><button class="btn danger" data-pdelete="${p.id}">Delete</button></div></div>`;
  }).join("") : '<div class="empty">Create a Lunch or Recess playlist, then choose it in Schedules.</div>';
  document.querySelectorAll("[data-pplay]").forEach(b => b.onclick = async () => {
    if (!state.selectedOutput) { toast("Choose an output on the Player tab first.", true); return; }
    b.disabled = true;
    try {
      await api(`api/playlists/${b.dataset.pplay}/play`, {method: "POST", body: JSON.stringify({entity_id: state.selectedOutput, browser_host: location.hostname})});
      toast(`Playlist started on ${selectedOutput()?.name || state.selectedOutput}.`);
      await poll();
    } catch (e) { toast(e.message, true); } finally { b.disabled = false; }
  });
  document.querySelectorAll("[data-pedit]").forEach(b => b.onclick = async () => { await loadAllMedia(); openPlaylist(b.dataset.pedit); });
  document.querySelectorAll("[data-pdelete]").forEach(b => b.onclick = async () => {
    const p = state.playlists.find(p => p.id === b.dataset.pdelete);
    if (!confirm(`Delete "${p.name}"?`)) return;
    try {
      await api(`api/playlists/${p.id}`, {method: "DELETE"});
      state.playlists = state.playlists.filter(item => item.id !== p.id);
      renderPlaylists();
    } catch (e) { toast(e.message, true); }
  });
}

function openPlaylist(id = "") {
  const playlist = state.playlists.find(p => p.id === id) || {name: "", tracks: [], repeat: false};
  const tracks = playlist.tracks.map(t => ({...t}));
  $("#modalRoot").innerHTML = `<div class="modal-bg"><div class="modal"><h2>${id ? "Edit" : "New"} playlist</h2><p>Add songs in the order you want them played. Use Schedules for automatic lunch and recess playback.</p><label class="label" for="playlistName">Name</label><input id="playlistName" class="field" value="${esc(playlist.name)}" placeholder="Lunch"><label class="label" for="playlistSong">Add a song</label><select id="playlistSong" class="select">${mediaOptions()}</select><button id="addSong" class="btn" style="margin-top:8px">＋ Add song</button><ol id="playlistTracks" style="padding-left:24px;max-height:300px;overflow:auto"></ol><label class="day-check"><input id="playlistRepeat" type="checkbox" ${playlist.repeat ? "checked" : ""}> Repeat until stopped</label><p class="small">Changes apply the next time this playlist starts. An active playlist keeps its current song order.</p><div class="modal-actions"><button id="cancelPlaylist" class="btn">Cancel</button><button id="savePlaylist" class="btn primary">Save playlist</button></div></div></div>`;
  const renderTracks = () => {
    $("#playlistTracks").innerHTML = tracks.map((t, i) => `<li style="margin:10px 0"><div style="overflow-wrap:anywhere">${esc(t.path)} <span class="small">(${t.source === "ha" ? "Home Assistant" : "Library"})</span></div><button class="mini" data-up="${i}" aria-label="Move song ${i + 1} up" ${i === 0 ? "disabled" : ""}>↑</button> <button class="mini" data-down="${i}" aria-label="Move song ${i + 1} down" ${i === tracks.length - 1 ? "disabled" : ""}>↓</button> <button class="mini" data-remove="${i}" aria-label="Remove song ${i + 1}">Remove</button></li>`).join("");
    document.querySelectorAll("[data-up]").forEach(b => b.onclick = () => { const i = +b.dataset.up; [tracks[i-1], tracks[i]] = [tracks[i], tracks[i-1]]; renderTracks(); });
    document.querySelectorAll("[data-down]").forEach(b => b.onclick = () => { const i = +b.dataset.down; [tracks[i+1], tracks[i]] = [tracks[i], tracks[i+1]]; renderTracks(); });
    document.querySelectorAll("[data-remove]").forEach(b => b.onclick = () => { tracks.splice(+b.dataset.remove, 1); renderTracks(); });
  };
  renderTracks();
  $("#addSong").onclick = () => {
    const value = $("#playlistSong").value, pos = value.indexOf("|");
    if (pos < 0) { toast("Upload or add audio files first.", true); return; }
    if (tracks.length >= 500) { toast("A playlist can contain up to 500 songs.", true); return; }
    tracks.push({source: value.slice(0, pos), path: value.slice(pos + 1)});
    renderTracks();
  };
  $("#cancelPlaylist").onclick = () => $("#modalRoot").innerHTML = "";
  $("#savePlaylist").onclick = async () => {
    const b = $("#savePlaylist"); b.disabled = true;
    try {
      const d = await api(id ? `api/playlists/${id}` : "api/playlists", {method: id ? "PUT" : "POST", body: JSON.stringify({name: $("#playlistName").value, tracks, repeat: $("#playlistRepeat").checked})});
      if (id) state.playlists[state.playlists.findIndex(p => p.id === id)] = d.playlist;
      else state.playlists.push(d.playlist);
      $("#modalRoot").innerHTML = "";
      renderPlaylists(); renderSchedules(); toast("Playlist saved.");
    } catch (e) { toast(e.message, true); b.disabled = false; }
  };
}
$("#addPlaylist").onclick = async () => { await loadAllMedia(); openPlaylist(); };
bootstrap();
