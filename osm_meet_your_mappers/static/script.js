// ================================
// Constants and State Management
// ================================

const CONFIG = {
  DATE_SORT_DESC: true, // whether to sort the table by date descending
  MAX_TABLE_ROWS: 100, // max number of rows to display (all will always be available in CSV)
  MAX_BOX_DEGREES: 1, // max allowed size on each side for the user drawn bbox
  INITIAL_STATUS: "Welcome! Please log in with your OSM account to continue.",
};

const state = {
  currentBbox: null,
  currentData: null,
  osm: null,
};

// ================================
// DOM Elements
// ================================

const elements = {
  status: document.querySelector(".status-message"),
  meetMappersBtn: document.querySelector("#meetMappers"),
  progress: document.querySelector(".progress-indicator"),
  results: document.querySelector("#results"),
  export: {
    container: document.querySelector("#export-container"),
    button: document.querySelector(".export-csv-button"),
  },
  map: {
    drawRectBtn: document.querySelector("#drawRect"),
  },
  auth: {
    logInOutBtn: document.querySelector("#logInOut"),
  },
};

// ================================
// Utility Functions
// ================================

const utils = {
  formatCoordinate: (num) => num.toFixed(4),

  createBboxString: (bbox) => {
    const { minLon, minLat, maxLon, maxLat } = bbox;
    return `[${utils.formatCoordinate(minLon)}, ${utils.formatCoordinate(
      minLat
    )}] to [${utils.formatCoordinate(maxLon)}, ${utils.formatCoordinate(
      maxLat
    )}]`;
  },
};

function friendlyDate(utcInput) {
  let date;
  try {
    if (typeof utcInput === "string") {
      // Ensure the string is properly formatted for Date parsing
      date = new Date(utcInput);

      // Check if the date is valid
      if (isNaN(date.getTime())) {
        console.error("Invalid date string:", utcInput);
        return "Invalid Date";
      }
    } else if (utcInput instanceof Date) {
      date = utcInput;
    } else {
      console.error("Invalid date input type:", typeof utcInput);
      return "Invalid Date";
    }

    const now = new Date();
    const oneDay = 24 * 60 * 60 * 1000;
    const optionsTime = { hour: "2-digit", minute: "2-digit" };

    // If the date is today (in local time)
    if (now.toDateString() === date.toDateString()) {
      return `Today at ${date.toLocaleTimeString(undefined, optionsTime)}`;
    }
    const yesterday = new Date(now.getTime() - oneDay);
    if (yesterday.toDateString() === date.toDateString()) {
      return `Yesterday at ${date.toLocaleTimeString(undefined, optionsTime)}`;
    }
    return (
      date.toLocaleDateString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
      }) +
      " " +
      date.toLocaleTimeString(undefined, optionsTime)
    );
  } catch (error) {
    console.error("Error formatting date:", error, "Input was:", utcInput);
    return "Invalid Date";
  }
}

function updateStatus(message) {
  elements.status.textContent = message;
  elements.status.classList.add("flash");
  setTimeout(() => elements.status.classList.remove("flash"), 1000);
}

// ================================
// UI Handling
// ================================

const ui = {
  showLoader: () => {
    elements.meetMappersBtn.disabled = true;
    elements.progress.style.visibility = "visible";
    elements.progress.setAttribute("aria-hidden", "false");
    elements.status.innerHTML = '<span class="loader"></span> Loading data...';
  },

  hideLoader: () => {
    elements.meetMappersBtn.disabled = false;
    elements.progress.style.visibility = "hidden";
    elements.progress.setAttribute("aria-hidden", "true");
  },
};

// ================================
// Data Handling Functions
// ================================

const dataHandler = {
  async fetchMappers(bbox) {
    const params = new URLSearchParams({
      min_lon: bbox.minLon,
      max_lon: bbox.maxLon,
      min_lat: bbox.minLat,
      max_lat: bbox.maxLat,
    });
    const response = await fetch(`/mappers/?${params}`);
    return response.json();
  },

  displayMappers(data) {
    state.currentData = data;
    elements.export.container.style.display = data.length ? "block" : "none";

    // Define columns and create table structure (same as before)
    const columns = [
      { key: "username", label: "User", type: "string" },
      { key: "changeset_count", label: "Changeset Count", type: "number" },
      { key: "first_change", label: "First Change", type: "date" },
      { key: "last_change", label: "Last Change", type: "date" },
    ];

    const table = document.createElement("table");
    table.className = "sortable-table";
    const thead = document.createElement("thead");
    const tbody = document.createElement("tbody");

    const headerRow = document.createElement("tr");
    columns.forEach((col, index) => {
      const th = document.createElement("th");
      th.textContent = col.label;
      th.dataset.type = col.type;
      th.dataset.key = col.key;

      // Add sort direction indicator
      const indicator = document.createElement("span");
      indicator.className = "sort-indicator";
      th.appendChild(indicator);

      // Add click event for sorting
      th.addEventListener("click", () =>
        this.sortTable(table, index, col.type)
      );

      headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);

    const maxRows = CONFIG.MAX_TABLE_ROWS;
    data.slice(0, maxRows).forEach((item) => {
      const row = document.createElement("tr");

      columns.forEach((col) => {
        const td = document.createElement("td");
        const value = item[col.key];

        if (col.key === "username") {
          const link = document.createElement("a");
          link.href = `https://www.openstreetmap.org/user/${value}`;
          link.textContent = value;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          td.appendChild(link);
        } else if (col.type === "date") {
          td.textContent = friendlyDate(value);
          try {
            const timestamp = new Date(value).getTime();
            td.dataset.sortValue = timestamp;
          } catch (e) {
            console.error("Error setting sort value for date:", e);
            td.dataset.sortValue = 0;
          }
        } else if (col.type === "number") {
          td.textContent = value;
          td.dataset.sortValue = value;
        } else {
          td.textContent = value;
        }

        row.appendChild(td);
      });
      tbody.appendChild(row);
    });

    table.appendChild(thead);
    table.appendChild(tbody);

    elements.results.innerHTML = "";
    elements.results.appendChild(table);

    if (data.length > maxRows) {
      const notice = document.createElement("div");
      notice.className = "truncation-notice";
      notice.textContent = `Showing only the first ${maxRows} of ${data.length} rows. Download the CSV file to see all mappers!`;
      elements.results.appendChild(notice);
    }

    // Initial sort by changeset count (descending)
    this.sortTable(table, 1, "number", CONFIG.DATE_SORT_DESC);
  },

  exportToCsv() {
    if (!state.currentData || state.currentData.length === 0) {
      updateStatus("No data available for CSV export.");
      return;
    }

    const headers = [
      "username",
      "changeset_count",
      "first_change",
      "last_change",
    ];

    const csvContent = [
      headers.join(","),
      ...state.currentData.map((row) => {
        // Format dates for CSV
        const firstChange = row.first_change
          ? new Date(row.first_change).toISOString()
          : "";
        const lastChange = row.last_change
          ? new Date(row.last_change).toISOString()
          : "";
        return [
          `"${row.username}"`,
          row.changeset_count,
          firstChange,
          lastChange,
        ].join(",");
      }),
    ].join("\n");

    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);

    const link = document.createElement("a");
    link.href = url;
    link.download = "osm_mappers_export.csv";
    link.style.visibility = "hidden";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  },

  sortTable(table, columnIndex, dataType, forceDescending = false) {
    const tbody = table.querySelector("tbody");
    const rows = Array.from(tbody.querySelectorAll("tr"));
    const headers = table.querySelectorAll("th");
    const header = headers[columnIndex];

    // Determine sort direction
    let isDescending = header.classList.contains("sort-asc") || forceDescending;

    // Reset all headers
    headers.forEach((h) => {
      h.classList.remove("sort-asc", "sort-desc");
    });

    // Set new sort direction
    header.classList.add(isDescending ? "sort-desc" : "sort-asc");

    // Sort the rows
    rows.sort((rowA, rowB) => {
      const cellA = rowA.querySelectorAll("td")[columnIndex];
      const cellB = rowB.querySelectorAll("td")[columnIndex];

      let valueA, valueB;

      // Get appropriate values based on data type
      if (dataType === "number") {
        valueA = parseFloat(cellA.dataset.sortValue || cellA.textContent);
        valueB = parseFloat(cellB.dataset.sortValue || cellB.textContent);
      } else if (dataType === "date") {
        valueA = parseInt(cellA.dataset.sortValue) || 0;
        valueB = parseInt(cellB.dataset.sortValue) || 0;
      } else {
        valueA = cellA.textContent.toLowerCase();
        valueB = cellB.textContent.toLowerCase();
      }

      // Compare values
      if (valueA < valueB) return isDescending ? 1 : -1;
      if (valueA > valueB) return isDescending ? -1 : 1;
      return 0;
    });

    // Reorder the rows
    rows.forEach((row) => tbody.appendChild(row));
  },

  exportToCsv() {
    if (!state.currentData) return;

    const headers = [
      "username",
      "changeset_count",
      "first_change",
      "last_change",
    ];

    const csvContent = [
      headers.join(","),
      ...state.currentData.map((row) => {
        // Format dates for CSV
        let firstChange, lastChange;
        try {
          firstChange = new Date(row.first_change).toISOString();
        } catch (e) {
          firstChange = row.first_change || "";
        }

        try {
          lastChange = new Date(row.last_change).toISOString();
        } catch (e) {
          lastChange = row.last_change || "";
        }

        return [
          `"${row.username}"`,
          row.changeset_count,
          firstChange,
          lastChange,
        ].join(",");
      }),
    ].join("\n");

    // Create and trigger download
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);

    const link = document.createElement("a");
    link.href = url;
    link.download = "osm_mappers_export.csv";
    link.style.visibility = "hidden";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  },
};

// ================================
// Map & Drawing Integration
// ================================

let map, drawnItems, drawRectangle;

function initializeMap() {
  map = L.map("map", { zoomControl: false }).setView([51.505, -0.09], 13);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors",
  }).addTo(map);

  // Attempt geolocate
  if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const lat = position.coords.latitude;
        const lon = position.coords.longitude;
        map.setView([lat, lon], 10);
      },
      (error) => {
        console.error("Geolocation error:", error);
      },
      {
        enableHighAccuracy: false,
        timeout: 5000,
        maximumAge: 0,
      }
    );
  } else {
    console.log("Geolocation is not supported by this browser.");
  }

  // group to hold box
  drawnItems = new L.FeatureGroup();
  map.addLayer(drawnItems);

  // We're not using the native buttons so...
  drawRectangle = new L.Draw.Rectangle(map, {
    shapeOptions: {
      color: "#ff0000",
      weight: 2,
    },
  });

  // Listen
  map.on(L.Draw.Event.CREATED, (event) => {
    const layer = event.layer;
    // Clear any old boxes
    drawnItems.clearLayers();
    drawnItems.addLayer(layer);

    // Extract bounds
    const bounds = layer.getBounds();
    const sw = bounds.getSouthWest().wrap();
    const ne = bounds.getNorthEast().wrap();
    if (
      Math.abs(ne.lng - sw.lng) > CONFIG.MAX_BOX_DEGREES ||
      Math.abs(ne.lat - sw.lat) > CONFIG.MAX_BOX_DEGREES
    ) {
      state.currentBbox = null;
      drawnItems.clearLayers();
      updateStatus("Box is too huge, try something smaller.");
    } else {
      state.currentBbox = {
        minLat: sw.lat,
        minLon: sw.lng,
        maxLat: ne.lat,
        maxLon: ne.lng,
      };

      elements.meetMappersBtn.disabled = false;
      updateStatus("Bounding box OK!");
    }
  });
}

// ================================
// Sidebar Button Event Handlers
// ================================

function initializeSidebarButtons() {
  // trigger draw handler
  elements.map.drawRectBtn.addEventListener("click", () => {
    drawnItems.clearLayers();
    drawRectangle.enable();
  });
}

// ================================
// "Meet My Mappers" Button Handler
// ================================

async function handleMeetMappers() {
  if (!state.currentBbox) {
    updateStatus("Please draw a rectangle on the map to select an area.");
    return;
  }

  ui.showLoader();
  try {
    const data = await dataHandler.fetchMappers(state.currentBbox);
    updateStatus(`Success! Found ${data.length} mappers.`);
    dataHandler.displayMappers(data);
  } catch (error) {
    console.error("Error:", error);
    updateStatus(`Error: ${error.message}`);
  } finally {
    ui.hideLoader();
  }
}

// ================================
// Version Handling
// ================================

async function getAppVersion() {
  try {
    const response = await fetch("/version");
    if (!response.ok) throw new Error("Failed to fetch version");
    const data = await response.json();
    return data.version;
  } catch (error) {
    console.error("Error fetching version:", error);
    return "unknown";
  }
}

async function getLatestChangesetTimestamp() {
  try {
    const response = await fetch("/latest");
    if (!response.ok) throw new Error("Failed to fetch latest changeset");
    const data = await response.json();
    return friendlyDate(data.latest_timestamp);
  } catch (error) {
    console.error("Error fetching latest changeset date :", error);
  }
}

// ================================
// Auth Functions
// ================================

async function checkAuth() {
  try {
    const response = await fetch("/auth/check", {
      credentials: "include",
    });
    if (!response.ok) throw new Error("Not authenticated");
    const osm_user = await response.json();
    state.osm = osm_user;
    return osm_user;
  } catch (error) {
    state.osm = null;
    return null;
  }
}

function updateAuthUI() {
  const userDisplay = document.getElementById("user-display");
  if (state.osm) {
    elements.auth.logInOutBtn.textContent = "Log Out";
    elements.map.drawRectBtn.disabled = false;
    userDisplay.style.display = "block";
    userDisplay.querySelector(".username").textContent =
      state.osm.user.display_name;
  } else {
    elements.auth.logInOutBtn.textContent = "Log In with OSM";
    elements.map.drawRectBtn.disabled = true;
    elements.meetMappersBtn.disabled = true;
    userDisplay.style.display = "none";
  }
}

// ================================
// Initialization on DOM Ready
// ================================

document.addEventListener("DOMContentLoaded", async () => {
  // Check auth status, update UI, etc.
  await checkAuth();
  updateAuthUI();

  // Setup auth event listeners
  elements.auth.logInOutBtn.addEventListener("click", async (e) => {
    e.preventDefault();
    if (state.osm) {
      try {
        await fetch("/logout", {
          method: "POST",
          credentials: "include",
        });
        state.osm = null;
        updateAuthUI();
        updateStatus("Successfully logged out");
      } catch (error) {
        console.error("Logout failed:", error);
        updateStatus("Logout failed. Please try again.");
      }
    } else {
      window.location.href = "/login";
    }
  });

  // Set version in footer
  const versionElement = document.getElementById("app-version");
  versionElement.textContent = await getAppVersion();
  const latestElement = document.getElementById("latest");
  latestElement.textContent = await getLatestChangesetTimestamp();

  initializeMap();
  initializeSidebarButtons();
  elements.meetMappersBtn.addEventListener("click", handleMeetMappers);

  // Attach the CSV export listener once
  elements.export.button.addEventListener("click", () =>
    dataHandler.exportToCsv()
  );

  updateStatus(
    state.osm
      ? "Welcome back! Draw an area to see its mappers."
      : CONFIG.INITIAL_STATUS
  );
});
