// DOM Elements
const form = document.querySelector("form");
const log = document.querySelector("#log");
const osmUrlInput = document.querySelector(".osm-url-input");
const areaSelect = document.querySelector(".area-select");
const statusEl = document.querySelector(".status-message");
const submitButton = document.querySelector(".submit-button");
const progressBar = document.querySelector(".progress-indicator");
const resultsDiv = document.querySelector("#results");
const exportContainer = document.querySelector("#export-container");
const exportButton = document.querySelector(".export-csv-button");

// box sizes
const neighborhoodSqKm = 5;
const cityKm2 = 25;
const regionKm2 = 250;

let currentBbox = null;
let currentData = null; // Store the current data for export

// Add export button click handler
exportButton.addEventListener("click", exportToCsv);

function exportToCsv() {
  if (!currentData) return;

  const headers = ["user", "changeset_count", "first_change", "last_change"];
  const csvContent = [
    headers.join(","),
    ...currentData.map((row) =>
      [
        `"${row.user}"`,
        row.changeset_count,
        new Date(row.first_change).toISOString(),
        new Date(row.last_change).toISOString(),
      ].join(",")
    ),
  ].join("\n");

  const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
  const link = document.createElement("a");
  const url = URL.createObjectURL(blob);
  link.setAttribute("href", url);
  link.setAttribute("download", "osm_mappers_export.csv");
  link.style.visibility = "hidden";
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

// Event Listeners
form.addEventListener("submit", handleFormSubmit);

async function handleFormSubmit(event) {
  event.preventDefault();

  const formData = new FormData(form);
  const osmUrl = formData.get("osm_url");
  const areaType = formData.get("area_size");

  if (!validateOsmUrl(osmUrl)) {
    osmUrlInput.ariaInvalid = true;
    return;
  }
  osmUrlInput.ariaInvalid = false;

  try {
    await fetchMappers(osmUrl, areaType);
  } catch (error) {
    log.textContent = `Error: ${error.message}`;
    console.error("Form submission error:", error);
  }
}

// Validation and parsing functions
function validateOsmUrl(osmUrl) {
  return osmUrl.match(/#map=(\d+)\/(-?\d+\.\d+)\/(-?\d+\.\d+)/) !== null;
}

function osmUrlToCenter(osmUrl) {
  const match = osmUrl.match(/#map=(\d+)\/(-?\d+\.\d+)\/(-?\d+\.\d+)/);
  if (!match) {
    throw new Error("Invalid OSM URL format");
  }
  return {
    lat: parseFloat(match[2]),
    lon: parseFloat(match[3]),
  };
}

function computeBbox(center, areaType) {
  if (!center || !areaType) {
    throw new Error("Invalid center or area type");
  }
  let halfSideKm;
  if (areaType === "neighborhood") {
    halfSideKm = Math.sqrt(neighborhoodSqKm) / 2;
  } else if (areaType === "city") {
    halfSideKm = Math.sqrt(cityKm2) / 2;
  } else if (areaType === "region") {
    halfSideKm = Math.sqrt(regionKm2) / 2;
  } else {
    halfSideKm = 0.5;
  }
  // approximate sqkm calculation
  const latOffset = halfSideKm / 111;
  const lonOffset = halfSideKm / (111 * Math.cos((center.lat * Math.PI) / 180));
  return {
    minLat: center.lat - latOffset,
    maxLat: center.lat + latOffset,
    minLon: center.lon - lonOffset,
    maxLon: center.lon + lonOffset,
  };
}

// Render a sortable table using Tablesort.
function displayMappers(data) {
  currentData = data; // Store the data for export
  // data.sort((a, b) => new Date(b.last_change) - new Date(a.last_change));
  data.sort(data.changeset_count);

  resultsDiv.innerHTML = "";
  exportContainer.style.display = data.length > 0 ? "block" : "none";

  const table = document.createElement("table");

  // Define the columns with explicit types.
  const columns = [
    { key: "user", label: "User", type: "string" },
    { key: "changeset_count", label: "Changeset Count", type: "number" },
    { key: "first_change", label: "First Change", type: "date" },
    { key: "last_change", label: "Last Change", type: "date" },
  ];

  // Build the table header.
  const thead = document.createElement("thead");
  const headerRow = document.createElement("tr");
  columns.forEach((col) => {
    const th = document.createElement("th");
    th.textContent = col.label;
    if (col.key === "changeset_count") {
      th.setAttribute("data-sort-method", "number");
      th.setAttribute("data-sort-default", "");
    }
    headerRow.appendChild(th);
  });
  thead.appendChild(headerRow);
  table.appendChild(thead);

  // Build the table body.
  const tbody = document.createElement("tbody");
  data.forEach((item) => {
    const tr = document.createElement("tr");
    columns.forEach((col) => {
      const td = document.createElement("td");
      let value = item[col.key];
      if (col.type === "date") {
        const dateObj = new Date(value);
        td.textContent = dateObj.toLocaleString();
        td.setAttribute("data-sort", dateObj.getTime());
      } else {
        td.textContent = value;
      }
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  resultsDiv.appendChild(table);

  // Initialize Tablesort on the table.
  new Tablesort(table, { descending: true });
}

async function fetchMappers(osmUrl, areaType) {
  submitButton.disabled = true;
  progressBar.style.display = "block";
  progressBar.setAttribute("aria-hidden", "false");
  statusEl.innerHTML = '<span class="loader"></span> Loading data...';

  try {
    const center = osmUrlToCenter(osmUrl);
    currentBbox = computeBbox(center, areaType);

    const response = await fetch(
      `/mappers/?min_lon=${currentBbox.minLon}&max_lon=${currentBbox.maxLon}&min_lat=${currentBbox.minLat}&max_lat=${currentBbox.maxLat}`
    );
    const data = await response.json();
    statusEl.textContent = `Success! Found ${data.length} mappers`;
    displayMappers(data);
  } catch (error) {
    console.error("Error fetching mapper data:", error);
    statusEl.textContent = "Error fetching mapper data. Please try again.";
  } finally {
    submitButton.disabled = false;
    progressBar.style.display = "none";
    progressBar.setAttribute("aria-hidden", "true");
  }
}
