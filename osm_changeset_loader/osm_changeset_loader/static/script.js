// DOM Elements
const form = document.querySelector("form");
const log = document.querySelector("#log");
const osmUrlInput = document.getElementById("osmUrlInput");
const areaSelect = document.getElementById("areaSelect");
const statusEl = document.getElementById("status");
const fetchButton = document.getElementById("fetchButton");
const progressBar = document.getElementById("progressBar");
const resultsDiv = document.getElementById("results");

let currentBbox = null;

// Event Listeners
form.addEventListener("submit", handleFormSubmit);

async function handleFormSubmit(event) {
  event.preventDefault();
  
  const formData = new FormData(form);
  const osmUrl = formData.get("osm_url");
  const areaType = formData.get("area_size");
  
  if (!validateOsmUrl(osmUrl)) {
    log.textContent = "Error: Invalid OSM URL format";
    return;
  }
  
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
    lon: parseFloat(match[3])
  };
}

function computeBbox(center, areaType) {
  if (!center || !areaType) {
    throw new Error("Invalid center or area type");
  }
  let halfSideKm;
  if (areaType === "neighborhood") {
    halfSideKm = Math.sqrt(5) / 2;
  } else if (areaType === "city") {
    halfSideKm = Math.sqrt(25) / 2;
  } else if (areaType === "state") {
    halfSideKm = Math.sqrt(250) / 2;
  } else {
    halfSideKm = 0.5;
  }
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
  data.sort((a, b) => new Date(b.last_change) - new Date(a.last_change));

  const resultsDiv = document.getElementById("results");
  resultsDiv.innerHTML = "";

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
        //                    } else if (col.type === 'number') {
        //                        td.textContent = value;
        //                        td.setAttribute("data-sort", value);
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
  fetchButton.disabled = true;
  progressBar.style.display = "block";
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
    fetchButton.disabled = false;
  }
}
