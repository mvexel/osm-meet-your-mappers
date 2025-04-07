// ================================
// Constants and State Management
// ================================

const CONFIG = {
  DATE_SORT_DESC: true, // whether to sort the table by date descending
  MAX_TABLE_ROWS: 100, // max number of rows to display (all will always be available in CSV)
  MAX_BOX_DEGREES: 1, // max allowed size on each side for the user drawn bbox
  INITIAL_STATUS: "Welcome! Please log in with your OSM account to continue.",
  URL_PARAM_NAMES: {
    MIN_LAT: "minlat",
    MIN_LON: "minlon",
    MAX_LAT: "maxlat",
    MAX_LON: "maxlon",
  },
};

const state = {
  currentBbox: null,
  currentData: null,
  osm: null,
  urlUpdated: false, // Track if URL was updated to prevent loops
};

// ================================
// DOM Elements
// ================================

const elements = {
  status: document.querySelector(".status-message"),
  meetMappersBtn: document.querySelector("#meetMappers"),
  progress: document.querySelector(".progress-indicator"),
  results: document.querySelector("#results"),
  filter: {
    container: document.querySelector("#filter-container"),
    input: document.querySelector("#user-filter"),
  },
  export: {
    container: document.querySelector("#export-container"),
    button: document.querySelector(".export-csv-button"),
  },
  share: {
    button: document.querySelector("#shareButton"),
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

  // Simple hash function for polygon coordinates
  hashCoordinates: (coords) => {
    return btoa(JSON.stringify(coords)).replace(/=/g, '');
  },

  // Unhash coordinates
  unhashCoordinates: (hash) => {
    try {
      return JSON.parse(atob(hash));
    } catch (e) {
      return null;
    }
  },

  createBboxString: (bbox) => {
    if (bbox.polygon) {
      return "Custom Polygon Area";
    }
    const { minLon, minLat, maxLon, maxLat } = bbox;
    return `[${utils.formatCoordinate(minLon)}, ${utils.formatCoordinate(
      minLat
    )}] to [${utils.formatCoordinate(maxLon)}, ${utils.formatCoordinate(
      maxLat
    )}]`;
  },

  // Update URL with bbox or polygon parameters
  updateUrlWithBbox: (bbox) => {
    if (!bbox) return;

    const url = new URL(window.location);
    url.searchParams.delete(CONFIG.URL_PARAM_NAMES.MIN_LAT);
    url.searchParams.delete(CONFIG.URL_PARAM_NAMES.MIN_LON);
    url.searchParams.delete(CONFIG.URL_PARAM_NAMES.MAX_LAT);
    url.searchParams.delete(CONFIG.URL_PARAM_NAMES.MAX_LON);
    url.searchParams.delete('polygon');

    if (bbox.polygon) {
      // For polygons, we'll hash the coordinates
      const coords = bbox.polygon
        .replace('POLYGON((', '')
        .replace('))', '')
        .split(',')
        .map(pair => pair.split(' ').map(Number));
      const hash = utils.hashCoordinates(coords);
      url.searchParams.set('polygon', hash);
    } else {
      // For regular bbox
      url.searchParams.set(CONFIG.URL_PARAM_NAMES.MIN_LAT, bbox.minLat.toFixed(6));
      url.searchParams.set(CONFIG.URL_PARAM_NAMES.MIN_LON, bbox.minLon.toFixed(6));
      url.searchParams.set(CONFIG.URL_PARAM_NAMES.MAX_LAT, bbox.maxLat.toFixed(6));
      url.searchParams.set(CONFIG.URL_PARAM_NAMES.MAX_LON, bbox.maxLon.toFixed(6));
    }

    window.history.pushState({}, "", url);
    state.urlUpdated = true;
  },

  // Get bbox or polygon from URL parameters
  getBboxFromUrl: () => {
    const url = new URL(window.location);
    
    // Check for polygon first
    const polygonHash = url.searchParams.get('polygon');
    if (polygonHash) {
      const coords = utils.unhashCoordinates(polygonHash);
      if (!coords) return null;
      
      // Reconstruct WKT polygon
      const wktCoords = coords.map(c => c.join(' ')).join(',');
      return {
        polygon: `POLYGON((${wktCoords}))`
      };
    }

    // Fall back to bbox
    const minLat = parseFloat(url.searchParams.get(CONFIG.URL_PARAM_NAMES.MIN_LAT));
    const minLon = parseFloat(url.searchParams.get(CONFIG.URL_PARAM_NAMES.MIN_LON));
    const maxLat = parseFloat(url.searchParams.get(CONFIG.URL_PARAM_NAMES.MAX_LAT));
    const maxLon = parseFloat(url.searchParams.get(CONFIG.URL_PARAM_NAMES.MAX_LON));

    if (isNaN(minLat) || isNaN(minLon) || isNaN(maxLat) || isNaN(maxLon)) {
      return null;
    }

    if (
      Math.abs(maxLon - minLon) > CONFIG.MAX_BOX_DEGREES ||
      Math.abs(maxLat - minLat) > CONFIG.MAX_BOX_DEGREES
    ) {
      return null;
    }

    return { minLat, minLon, maxLat, maxLon };
  },
};

function setupAccessibilityAnnouncements() {
  const announcer = document.createElement("div");
  announcer.setAttribute("aria-live", "polite");
  announcer.setAttribute("aria-atomic", "true");
  announcer.className = "visually-hidden";
  announcer.id = "a11y-announcer";
  document.body.appendChild(announcer);
}

// Function to announce important changes to screen readers
function announce(message) {
  const announcer = document.getElementById("a11y-announcer");
  if (announcer) {
    announcer.textContent = message;
  }
}

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
  announce(message); // Announce the status message
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

  updateFooter: async () => {
    const versionElement = document.getElementById("app-version");
    versionElement.textContent = await getAppVersion();
    const latestElement = document.getElementById("latest");
    latestElement.textContent = await getLatestChangesetTimestamp();
  },
};

// ================================
// Data Handling Functions
// ================================

const dataHandler = {
  async fetchMappers(bbox) {
    const params = new URLSearchParams();
    
    if (bbox.polygon) {
      params.set('polygon', bbox.polygon);
    } else {
      params.set('min_lon', bbox.minLon);
      params.set('max_lon', bbox.maxLon);
      params.set('min_lat', bbox.minLat);
      params.set('max_lat', bbox.maxLat);
    }
    
    const response = await fetch(`/mappers/?${params}`);
    return response.json();
  },

  displayMappers(data, isFiltered = false) {
    if (!isFiltered) {
      // Only update the full dataset when not filtering
      state.currentData = data;
      // Clear filter when displaying new data
      elements.filter.input.value = "";
    }
    
    const hasData = data.length > 0;
    elements.export.container.style.display = hasData ? "block" : "none";
    
    // Enable/disable share button based on data
    elements.share.button.disabled = !hasData;

    // Show the filter container
    elements.filter.container.style.display = hasData ? "block" : "none";
    
    // Clear previous results
    elements.results.innerHTML = "";

    // Define columns and create table structure
    const columns = [
      { key: "username", label: "User", type: "string", showOsmchaLink: true },
      { key: "changeset_count", label: "Changeset Count", type: "number" },
      { key: "first_change", label: "First Change", type: "date" },
      { key: "last_change", label: "Last Change", type: "date" },
    ];

    const table = document.createElement("table");
    table.className = "sortable-table";
    table.setAttribute("aria-label", "OpenStreetMap mappers in selected area");

    // Add a caption for screen readers
    const caption = document.createElement("caption");
    caption.className = "visually-hidden";
    caption.textContent = "List of OpenStreetMap mappers in the selected area";
    table.appendChild(caption);

    const thead = document.createElement("thead");
    const tbody = document.createElement("tbody");

    const headerRow = document.createElement("tr");
    columns.forEach((col, index) => {
      const th = document.createElement("th");
      th.setAttribute("aria-sort", "none");
      th.dataset.type = col.type;
      th.dataset.key = col.key;

      // Create header content container
      const headerContent = document.createElement("div");
      headerContent.className = "header-content";
      headerContent.textContent = col.label;

      // We don't need the OSMCha icon in the header anymore

      th.appendChild(headerContent);

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
          // Create container for links
          const linkContainer = document.createElement("div");
          linkContainer.className = "user-links";

          // OSM profile link
          const osmLink = document.createElement("a");
          osmLink.href = `https://www.openstreetmap.org/user/${value}`;
          osmLink.textContent = value;
          osmLink.target = "_blank";
          osmLink.rel = "noopener noreferrer";
          osmLink.className = "osm-link";
          linkContainer.appendChild(osmLink);

          // Create a container for the icon links
          const iconContainer = document.createElement("div");
          iconContainer.className = "icon-links";
          linkContainer.appendChild(iconContainer);

          // OSM Messaging link
          const messagingLink = document.createElement("a");
          messagingLink.href = `https://www.openstreetmap.org/messages/new/${value}`;
          messagingLink.innerHTML = `<span title="Send a message to ${value} on OSM">👋🏻</span>`;
          messagingLink.target = "_blank";
          messagingLink.rel = "noopener noreferrer";
          messagingLink.className = "user-link";
          iconContainer.appendChild(messagingLink);

          // OSMCha link
          if (state.currentBbox) {
            const osmchaLink = document.createElement("a");
            const bbox = `${state.currentBbox.minLon},${state.currentBbox.minLat},${state.currentBbox.maxLon},${state.currentBbox.maxLat}`;

            // Calculate date 1 year ago for the filter
            const oneYearAgo = new Date();
            oneYearAgo.setFullYear(oneYearAgo.getFullYear() - 1);
            const dateString = oneYearAgo.toISOString().split("T")[0]; // Format as YYYY-MM-DD

            osmchaLink.href = `https://osmcha.org/?filters=%7B%22users%22%3A%5B%7B%22label%22%3A%22${value}%22%2C%22value%22%3A%22${value}%22%7D%5D%2C%22in_bbox%22%3A%5B%7B%22label%22%3A%22${bbox}%22%2C%22value%22%3A%22${bbox}%22%7D%5D%2C%22date__gte%22%3A%5B%7B%22label%22%3A%22${dateString}%22%2C%22value%22%3A%22${dateString}%22%7D%5D%7D`;
            osmchaLink.innerHTML = `<span title="View in OSMCha">📊</span>`;
            osmchaLink.target = "_blank";
            osmchaLink.rel = "noopener noreferrer";
            osmchaLink.className = "user-link";
            iconContainer.appendChild(osmchaLink);
          }

          td.appendChild(linkContainer);
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
      
      if (elements.filter.input.value.trim()) {
        // When filtering
        notice.textContent = `Showing ${Math.min(maxRows, data.length)} of ${data.length} matching mappers. Download the CSV file to see all results!`;
      } else {
        // Normal case (no filter)
        notice.textContent = `Showing only the first ${maxRows} of ${data.length} mappers. Download the CSV file to see all mappers!`;
      }
      
      elements.results.appendChild(notice);
    }

    // Initial sort by changeset count (descending)
    this.sortTable(table, 1, "number", CONFIG.DATE_SORT_DESC);

    // Make sure the filter works with the initial data
    if (elements.filter.input.value.trim()) {
      const searchTerm = elements.filter.input.value.toLowerCase();
      const rows = table.querySelectorAll("tbody tr");

      rows.forEach((row) => {
        const usernameCell = row.querySelector("td");
        const usernameLink = usernameCell.querySelector("a.osm-link");
        const username = usernameLink
          ? usernameLink.textContent.toLowerCase()
          : "";

        row.style.display = username.includes(searchTerm) ? "" : "none";
      });
    }
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
      h.setAttribute("aria-sort", "none");
    });

    // Set new sort direction
    header.classList.add(isDescending ? "sort-desc" : "sort-asc");
    header.setAttribute("aria-sort", isDescending ? "descending" : "ascending");

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

let map, drawnItems, drawRectangle, drawPolygon;

function initializeMap() {
  map = L.map("map", { zoomControl: false }).setView([51.505, -0.09], 13);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors",
  }).addTo(map);

  // group to hold box
  drawnItems = new L.FeatureGroup();
  map.addLayer(drawnItems);

  // Check for bbox or polygon in URL first
  const urlBbox = utils.getBboxFromUrl();
  if (urlBbox) {
    if (urlBbox.polygon) {
      // Handle polygon
      const coords = urlBbox.polygon
        .replace('POLYGON((', '')
        .replace('))', '')
        .split(',')
        .map(pair => {
          const [lng, lat] = pair.split(' ').map(Number);
          return [lat, lng];
        });
        
      const layer = L.polygon(coords, {
        color: "#ff0000",
        weight: 2,
        fillOpacity: 0.2
      });
      drawnItems.addLayer(layer);
        
      // Set the bbox in state
      state.currentBbox = urlBbox;
      state.urlUpdated = true;
        
      // Zoom to polygon bounds
      map.fitBounds(layer.getBounds());
        
      // Enable the Meet Mappers button
      elements.meetMappersBtn.disabled = false;
      updateStatus("Polygon loaded from URL!");
    } else {
      // Handle regular bbox
      const bounds = L.latLngBounds(
        L.latLng(urlBbox.minLat, urlBbox.minLon),
        L.latLng(urlBbox.maxLat, urlBbox.maxLon)
      );

      // Add the rectangle to the map
      const layer = L.rectangle(bounds, {
        color: "#ff0000",
        weight: 2,
      });
      drawnItems.addLayer(layer);

      // Set the bbox in state
      state.currentBbox = urlBbox;
      state.urlUpdated = true;

      // Zoom to the bbox
      map.fitBounds(bounds);

      // Enable the Meet Mappers button
      elements.meetMappersBtn.disabled = false;
      updateStatus("Bounding box loaded from URL!");
    }
  } else {
    // Attempt geolocate if no bbox in URL
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
  }

  // Initialize drawing tools
  drawRectangle = new L.Draw.Rectangle(map, {
    shapeOptions: {
      color: "#ff0000",
      weight: 2,
    },
  });

  drawPolygon = new L.Draw.Polygon(map, {
    shapeOptions: {
      color: "#ff0000",
      weight: 2,
      fillOpacity: 0.2
    },
    allowIntersection: false,
    showArea: true
  });

  // Listen
  map.on(L.Draw.Event.CREATED, (event) => {
    const layer = event.layer;
    // Clear any old boxes
    drawnItems.clearLayers();
    drawnItems.addLayer(layer);

    // Extract bounds
    let bbox;
    if (layer instanceof L.Rectangle) {
      const bounds = layer.getBounds();
      const sw = bounds.getSouthWest().wrap();
      const ne = bounds.getNorthEast().wrap();
      if (
        Math.abs(ne.lng - sw.lng) > CONFIG.MAX_BOX_DEGREES ||
        Math.abs(ne.lat - sw.lat) > CONFIG.MAX_BOX_DEGREES
      ) {
        state.currentBbox = null;
        drawnItems.clearLayers();
        updateStatus("Area is too large, try something smaller.");
        return;
      }
      bbox = {
        minLat: sw.lat,
        minLon: sw.lng,
        maxLat: ne.lat,
        maxLon: ne.lng,
      };
    } else if (layer instanceof L.Polygon) {
      const bounds = layer.getBounds();
      const sw = bounds.getSouthWest().wrap();
      const ne = bounds.getNorthEast().wrap();
      if (
        Math.abs(ne.lng - sw.lng) > CONFIG.MAX_BOX_DEGREES ||
        Math.abs(ne.lat - sw.lat) > CONFIG.MAX_BOX_DEGREES
      ) {
        state.currentBbox = null;
        drawnItems.clearLayers();
        updateStatus("Area is too large, try something smaller.");
        return;
      }
      // Convert polygon to WKT format
      const points = layer.getLatLngs()[0];
      // Create coordinate string and ensure polygon is closed by repeating first point
      const coords = points.map(ll => `${ll.lng} ${ll.lat}`).join(',');
      const firstPoint = `${points[0].lng} ${points[0].lat}`;
      bbox = {
        polygon: `POLYGON((${coords},${firstPoint}))`
      };
    }
    
    if (bbox) {
      state.currentBbox = bbox;

      // Update URL with the new bbox
      utils.updateUrlWithBbox(state.currentBbox);

      elements.meetMappersBtn.disabled = false;
      updateStatus("Bounding box OK!");
    }
  });
}

// ================================
// Sidebar Button Event Handlers
// ================================

function initializeSidebarButtons() {
  // Rectangle draw handler
  elements.map.drawRectBtn.addEventListener("click", () => {
    drawnItems.clearLayers();
    // Disable polygon drawing first
    if (drawPolygon._enabled) {
      drawPolygon.disable();
    }
    drawRectangle.enable();
  });

  // Polygon draw handler
  const drawPolygonBtn = document.getElementById("drawPolygon");
  drawPolygonBtn.addEventListener("click", () => {
    drawnItems.clearLayers();
    // Disable rectangle drawing first
    if (drawRectangle._enabled) {
      drawRectangle.disable();
    }
    drawPolygon.enable();
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
  ui.updateFooter();

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
    document.getElementById("drawPolygon").disabled = false;
    userDisplay.querySelector(".logged-in-as").textContent = "Logged in as";
    userDisplay.querySelector(".username").textContent =
      `@` + state.osm.user.display_name;
  } else {
    elements.auth.logInOutBtn.textContent = "Log In with OSM";
    elements.map.drawRectBtn.disabled = true;
    document.getElementById("drawPolygon").disabled = true;
    elements.meetMappersBtn.disabled = true;
    userDisplay.querySelector(".logged-in-as").textContent = "Not logged in";
    userDisplay.querySelector(".username").textContent = "";
  }
}

// ================================
// Initialization on DOM Ready
// ================================

document.addEventListener("DOMContentLoaded", async () => {
  // Set up filter functionality
  elements.filter.input.addEventListener("input", (e) => {
    setupAccessibilityAnnouncements();
    applyFilter();
  });

  // Function to apply the current filter
  function applyFilter() {
    if (!state.currentData) return;

    const searchTerm = elements.filter.input.value.toLowerCase();
    
    if (searchTerm === "") {
      // If no filter, just display the original table with pagination
      dataHandler.displayMappers(state.currentData);
      return;
    }
    
    // Filter the full dataset
    const filteredData = state.currentData.filter(item => 
      item.username.toLowerCase().includes(searchTerm)
    );
    
    // Display the filtered data
    dataHandler.displayMappers(filteredData, true);
    
    // Update status to show filter results
    updateStatus(`Found ${filteredData.length} mappers matching "${searchTerm}"`);
  }

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
        
        // Clear the table and reset UI elements
        elements.results.innerHTML = "";
        elements.filter.container.style.display = "none";
        elements.export.container.style.display = "none";
        elements.share.button.disabled = true;
        state.currentData = null;
        
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
  ui.updateFooter();

  // Initialize map
  initializeMap();
  initializeSidebarButtons();
  elements.meetMappersBtn.addEventListener("click", handleMeetMappers);

  // Handle popstate events (back/forward browser navigation)
  window.addEventListener("popstate", () => {
    // Clear current bbox and drawn items
    state.currentBbox = null;
    drawnItems.clearLayers();
    
    // Disable share button when navigation occurs
    elements.share.button.disabled = true;

    // Check for bbox in URL
    const urlBbox = utils.getBboxFromUrl();
    if (urlBbox) {
      // Create a rectangle from the URL parameters
      const bounds = L.latLngBounds(
        L.latLng(urlBbox.minLat, urlBbox.minLon),
        L.latLng(urlBbox.maxLat, urlBbox.maxLon)
      );

      // Add the rectangle to the map
      const layer = L.rectangle(bounds, {
        color: "#ff0000",
        weight: 2,
      });
      drawnItems.addLayer(layer);

      // Set the bbox in state
      state.currentBbox = urlBbox;

      // Zoom to the bbox
      map.fitBounds(bounds);

      // Enable the Meet Mappers button
      elements.meetMappersBtn.disabled = false;
      updateStatus("Bounding box loaded from URL!");
    }
  });

  // Create toast element for notifications
  const toast = document.createElement('div');
  toast.className = 'toast';
  document.body.appendChild(toast);

  // Function to show toast notification
  function showToast(message) {
    toast.textContent = message;
    toast.className = 'toast show';
    setTimeout(() => {
      toast.className = toast.className.replace('show', '');
    }, 3000);
  }

  // Share button functionality
  function handleShare() {
    if (!state.currentBbox || !state.currentData || state.currentData.length === 0) return;
    
    try {
      navigator.clipboard.writeText(window.location.href).then(() => {
        showToast('Link copied to clipboard!');
        announce('Link copied to clipboard!');
      }, (err) => {
        console.error('Could not copy text: ', err);
        showToast('Failed to copy link');
      });
    } catch (err) {
      console.error('Clipboard API not available: ', err);
      // Fallback for browsers that don't support clipboard API
      const dummy = document.createElement('textarea');
      document.body.appendChild(dummy);
      dummy.value = window.location.href;
      dummy.select();
      document.execCommand('copy');
      document.body.removeChild(dummy);
      showToast('Link copied to clipboard!');
      announce('Link copied to clipboard!');
    }
  }

  // Attach the CSV export listener once
  elements.export.button.addEventListener("click", () =>
    dataHandler.exportToCsv()
  );
  
  // Attach the share button listener
  elements.share.button.addEventListener("click", handleShare);

  updateStatus(
    state.osm
      ? "Welcome back! Draw an area to see its mappers."
      : CONFIG.INITIAL_STATUS
  );
});
