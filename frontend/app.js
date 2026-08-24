// ShowPass Application Frontend Logic

const API_BASE = "/api";
let currentToken = localStorage.getItem("token") || null;
let currentUser = null;
let currentView = "events";
let seatMapEventId = null;
let seatMapWebSocket = null;
let selectedSeatIds = [];
let activeHeldSeatIds = [];
let holdTimerInterval = null;
let holdExpiresAt = null;
let activeOfferId = null; // Stored waitlist offer ID for home page banner
let seatMapPricing = null; // Stored event category pricing dictionary

// Helper to update the waitlist price label based on category selection
function updateWaitlistPrice() {
    const categorySelect = document.getElementById("waitlist-category");
    if (!categorySelect) return;
    const category = categorySelect.value;
    if (!category || !seatMapPricing) {
        document.getElementById("waitlist-price").innerText = "$0.00";
        return;
    }
    const price = seatMapPricing[category] || 0.0;
    document.getElementById("waitlist-price").innerText = `$${price.toFixed(2)}`;
}

// Helper to check for active waitlist offers
async function checkForActiveOffers() {
    if (!currentUser || currentUser.role !== "customer") {
        hideOfferBanner();
        return;
    }
    
    try {
        const res = await fetchWithAuth(`${API_BASE}/customer/active-offers`);
        if (res.ok) {
            const offer = await res.json();
            if (offer) {
                showOfferBanner(offer);
            } else {
                hideOfferBanner();
            }
        }
    } catch (e) {
        console.error("Error checking active offers:", e);
    }
}

function showOfferBanner(offer) {
    activeOfferId = offer.id;
    document.getElementById("banner-offer-event").innerText = `${offer.event_title} (${offer.seat_desc})`;
    document.getElementById("waitlist-offer-banner").classList.remove("hidden");
}

function hideOfferBanner() {
    document.getElementById("waitlist-offer-banner").classList.add("hidden");
    activeOfferId = null;
}

function goToActiveOffer() {
    if (activeOfferId) {
        window.location.hash = `#claim-offer?offer_id=${activeOfferId}`;
    }
}

// Helper to parse dates in UTC (appending 'Z' if missing timezone suffix)
function parseUTCDate(dateStr) {
    if (!dateStr) return null;
    if (!dateStr.endsWith("Z") && !dateStr.includes("+")) {
        return new Date(dateStr + "Z");
    }
    return new Date(dateStr);
}

// Initial Setup
document.addEventListener("DOMContentLoaded", async () => {
    await checkAuthOnLoad(); // Verify auth state first to resolve routing race conditions
    setupRouter();
    loadEvents();
});

// Routing and Navigation
function setupRouter() {
    // Check URL hashes (e.g., #claim-offer?offer_id=X)
    window.addEventListener("hashchange", handleHashRouting);
    handleHashRouting();
}

function handleHashRouting() {
    const hash = window.location.hash;
    if (hash.startsWith("#claim-offer")) {
        const urlParams = new URLSearchParams(hash.split("?")[1]);
        const offerId = urlParams.get("offer_id");
        if (offerId) {
            loadOfferPage(offerId);
            return;
        }
    }
    navigate(currentView);
}

function navigate(viewName) {
    currentView = viewName;
    
    // Hide all views
    document.querySelectorAll("main > section").forEach(section => {
        section.classList.add("hidden");
    });
    
    // Cleanup WebSocket if leaving seat map
    if (viewName !== "seatmap" && seatMapWebSocket) {
        seatMapWebSocket.close();
        seatMapWebSocket = null;
    }
    if (viewName !== "seatmap") {
        clearInterval(holdTimerInterval);
        selectedSeatIds = [];
        activeHeldSeatIds = [];
    }

    // Show selected view
    const viewSection = document.getElementById(`view-${viewName}`);
    if (viewSection) {
        viewSection.classList.remove("hidden");
    }

    // Specific view actions
    if (viewName === "events") {
        loadEvents();
        checkForActiveOffers();
    } else if (viewName === "my-bookings") {
        loadCustomerBookings();
    } else if (viewName === "organiser-dash") {
        loadOrganiserDashboard();
    } else if (viewName === "admin-dash") {
        loadAdminDashboard();
    }
}

// Authentication Helpers
async function checkAuthOnLoad() {
    if (currentToken) {
        try {
            const res = await fetchWithAuth(`${API_BASE}/auth/me`);
            if (res.ok) {
                currentUser = await res.json();
                updateHeaderForLoggedInUser();
                await checkForActiveOffers(); // Check for pending waitlist offers on startup
                return;
            }
        } catch (e) {
            console.error("Auth check failed:", e);
        }
    }
    logout(false); // Clear storage and show logged out layout
}

function updateHeaderForLoggedInUser() {
    document.getElementById("btn-login-view").classList.add("hidden");
    document.getElementById("btn-logout").classList.remove("hidden");
    
    const userDisplay = document.getElementById("user-display");
    userDisplay.innerText = `${currentUser.email} (${currentUser.role.toUpperCase()})`;
    userDisplay.classList.remove("hidden");
    
    // Show appropriate nav items
    const nav = document.getElementById("nav-links");
    nav.classList.remove("hidden");
    
    document.getElementById("nav-my-bookings").classList.add("hidden");
    document.getElementById("nav-organiser-dash").classList.add("hidden");
    document.getElementById("nav-admin-dash").classList.add("hidden");

    if (currentUser.role === "customer" || currentUser.role === "admin") {
        document.getElementById("nav-my-bookings").classList.remove("hidden");
    }
    if (currentUser.role === "organiser" || currentUser.role === "admin") {
        document.getElementById("nav-organiser-dash").classList.remove("hidden");
    }
    if (currentUser.role === "admin") {
        document.getElementById("nav-admin-dash").classList.remove("hidden");
    }
}

function logout(redirect = true) {
    localStorage.removeItem("token");
    currentToken = null;
    currentUser = null;
    
    document.getElementById("btn-login-view").classList.remove("hidden");
    document.getElementById("btn-logout").classList.add("hidden");
    document.getElementById("user-display").classList.add("hidden");
    document.getElementById("nav-links").classList.add("hidden");
    
    if (redirect) {
        showAlert("Logged out successfully", "success");
        navigate("events");
    }
}

function toggleAuthTab(tab) {
    if (tab === "login") {
        document.getElementById("tab-login").className = "text-lg font-bold text-indigo-600 border-b-2 border-indigo-600 pb-1";
        document.getElementById("tab-register").className = "text-lg font-bold text-gray-400 pb-1";
        document.getElementById("form-login").classList.remove("hidden");
        document.getElementById("form-register").classList.add("hidden");
    } else {
        document.getElementById("tab-login").className = "text-lg font-bold text-gray-400 pb-1";
        document.getElementById("tab-register").className = "text-lg font-bold text-indigo-600 border-b-2 border-indigo-600 pb-1";
        document.getElementById("form-login").classList.add("hidden");
        document.getElementById("form-register").classList.remove("hidden");
    }
}

async function handleLogin(e) {
    e.preventDefault();
    const email = document.getElementById("login-email").value;
    const password = document.getElementById("login-password").value;
    
    const body = new URLSearchParams();
    body.append("username", email);
    body.append("password", password);

    try {
        const response = await fetch(`${API_BASE}/auth/login`, {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded" },
            body: body
        });

        if (response.ok) {
            const data = await response.json();
            currentToken = data.access_token;
            localStorage.setItem("token", currentToken);
            
            await checkAuthOnLoad();
            showAlert("Logged in successfully!", "success");
            
            // If the user arrived via a waitlist claim link, redirect them back to the claim screen
            if (window.location.hash.startsWith("#claim-offer")) {
                handleHashRouting();
            } else {
                navigate("events");
            }
            
            // Clear inputs
            document.getElementById("login-email").value = "";
            document.getElementById("login-password").value = "";
        } else {
            const error = await response.json();
            showAlert(error.detail || "Authentication failed", "error");
        }
    } catch (err) {
        showAlert("Error connecting to login server", "error");
    }
}

async function handleRegister(e) {
    e.preventDefault();
    const email = document.getElementById("register-email").value;
    const password = document.getElementById("register-password").value;
    const role = document.getElementById("register-role").value;

    try {
        const response = await fetch(`${API_BASE}/auth/register`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, password, role })
        });

        if (response.ok) {
            showAlert("Account created! Please sign in.", "success");
            toggleAuthTab("login");
            
            // Clear inputs
            document.getElementById("register-email").value = "";
            document.getElementById("register-password").value = "";
        } else {
            const error = await response.json();
            showAlert(error.detail || "Registration failed", "error");
        }
    } catch (err) {
        showAlert("Error registering new account", "error");
    }
}

// Fetch Wrapper with Token Authorization
async function fetchWithAuth(url, options = {}) {
    const headers = options.headers || {};
    if (currentToken) {
        headers["Authorization"] = `Bearer ${currentToken}`;
    }
    return fetch(url, { ...options, headers });
}

// ----------------- CUSTOMER: BROWSE EVENTS -----------------
async function loadEvents() {
    const searchVal = document.getElementById("event-search").value;
    let url = `${API_BASE}/events`;
    if (searchVal) {
        url += `?title=${encodeURIComponent(searchVal)}`;
    }

    try {
        const response = await fetch(url);
        const events = await response.json();
        const grid = document.getElementById("event-grid");
        grid.innerHTML = "";

        if (events.length === 0) {
            grid.innerHTML = `<p class="col-span-full text-center text-gray-500 py-10">No events found matching your query.</p>`;
            return;
        }

        events.forEach(event => {
            const pricing = JSON.parse(event.pricing);
            const pricingStr = Object.entries(pricing).map(([cat, val]) => `${cat}: $${val}`).join(" | ");
            
            const card = document.createElement("div");
            card.className = "bg-white rounded-lg shadow-sm border border-gray-100 overflow-hidden hover:shadow-md transition duration-200 cursor-pointer flex flex-col justify-between";
            card.onclick = () => openSeatMap(event.id);
            
            card.innerHTML = `
                <div class="p-6 space-y-3">
                    <h3 class="text-xl font-bold text-gray-900 leading-tight">${event.title}</h3>
                    <p class="text-sm text-gray-500 line-clamp-3">${event.description || "No description available."}</p>
                    <div class="flex items-center text-xs font-semibold text-indigo-600 bg-indigo-50 px-2.5 py-1 rounded w-fit">
                        <svg class="h-4 w-4 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                        </svg>
                        ${event.date} at ${event.time}
                    </div>
                </div>
                <div class="bg-gray-50 px-6 py-4 border-t text-xs font-medium text-gray-500 flex justify-between items-center">
                    <span>${pricingStr}</span>
                    <span class="text-indigo-600 font-bold">Book Tickets &rarr;</span>
                </div>
            `;
            grid.appendChild(card);
        });
    } catch (err) {
        console.error("Error loading events:", err);
    }
}

// ----------------- CUSTOMER: SEAT MAP VIEW -----------------
async function openSeatMap(eventId) {
    if (!currentUser) {
        showAlert("Please log in to hold or book seats.", "error");
        navigate("login");
        return;
    }
    
    seatMapEventId = eventId;
    selectedSeatIds = [];
    activeHeldSeatIds = [];
    clearInterval(holdTimerInterval);
    document.getElementById("checkout-timer-panel").classList.add("hidden");
    document.getElementById("btn-book-seats").classList.add("hidden");
    document.getElementById("btn-release-hold").classList.add("hidden");
    document.getElementById("btn-hold-seats").classList.remove("hidden");
    
    try {
        // Fetch event meta
        const metaRes = await fetch(`${API_BASE}/events/${eventId}`);
        if (!metaRes.ok) throw new Error("Event not found");
        const event = await metaRes.json();
        
        document.getElementById("seatmap-event-title").innerText = event.title;
        document.getElementById("seatmap-event-meta").innerText = `${event.date} at ${event.time}`;
        
        // Populate waitlist category options
        const waitlistSel = document.getElementById("waitlist-category");
        waitlistSel.innerHTML = "";
        const pricing = JSON.parse(event.pricing);
        seatMapPricing = pricing; // Store pricing dictionary
        Object.keys(pricing).forEach(cat => {
            const opt = document.createElement("option");
            opt.value = cat;
            opt.innerText = `${cat} ($${pricing[cat]})`;
            waitlistSel.appendChild(opt);
        });
        updateWaitlistPrice(); // Load initial price tag

        // Initialize seat map grid
        await reloadSeatGrid(eventId, pricing);
        
        // Connect websocket for real-time seat updates
        connectWebSocket(eventId, pricing);

        navigate("seatmap");
    } catch (e) {
        showAlert(e.message, "error");
    }
}

async function reloadSeatGrid(eventId, pricing) {
    const res = await fetch(`${API_BASE}/events/${eventId}/seats`);
    if (!res.ok) return;
    const seats = await res.json();
    
    renderSeatGrid(seats, pricing);
}

function renderSeatGrid(seats, pricing) {
    const container = document.getElementById("seat-grid-container");
    container.innerHTML = "";
    
    // Group seats by row_name
    const rowsMap = {};
    seats.forEach(seat => {
        if (!rowsMap[seat.row_name]) {
            rowsMap[seat.row_name] = [];
        }
        rowsMap[seat.row_name].push(seat);
    });
    
    // Sort rows alphabetically
    const rowsSorted = Object.keys(rowsMap).sort();
    
    const table = document.createElement("table");
    table.className = "border-separate border-spacing-2 text-center select-none mx-auto";
    
    rowsSorted.forEach(rowName => {
        const tr = document.createElement("tr");
        
        // Row Label Header Left
        const tdRowHeader = document.createElement("td");
        tdRowHeader.className = "pr-4 font-bold text-gray-500 text-sm";
        tdRowHeader.innerText = rowName;
        tr.appendChild(tdRowHeader);
        
        // Sort seats numerically
        const seatsSorted = rowsMap[rowName].sort((a, b) => a.seat_number - b.seat_number);
        
        seatsSorted.forEach(seat => {
            const td = document.createElement("td");
            
            // Check status styling
            let baseColorClass = "bg-indigo-200 border-indigo-300 hover:bg-indigo-300"; // Premium default
            if (seat.category === "Standard") {
                baseColorClass = "bg-sky-200 border-sky-300 hover:bg-sky-300";
            }
            
            if (seat.status === "held") {
                baseColorClass = "bg-amber-400 border-amber-500 cursor-not-allowed";
            } else if (seat.status === "booked") {
                baseColorClass = "bg-rose-500 border-rose-600 cursor-not-allowed text-white";
            }
            
            // Check if selected or held by current user in local session
            const isSelected = selectedSeatIds.includes(seat.seat_id);
            const isSelfHeld = activeHeldSeatIds.includes(seat.seat_id);
            
            if (isSelected) {
                baseColorClass = "bg-emerald-500 border-emerald-600 hover:bg-emerald-600 text-white";
            } else if (isSelfHeld) {
                baseColorClass = "bg-emerald-600 border-emerald-700 hover:bg-emerald-700 text-white font-bold animate-pulse";
            }

            td.className = `${baseColorClass} w-9 h-9 border rounded-md text-xs font-semibold flex items-center justify-center cursor-pointer transition shadow-sm`;
            td.innerText = seat.seat_number;
            td.dataset.seatId = seat.seat_id;
            td.dataset.category = seat.category;
            td.dataset.price = pricing[seat.category] || 0.0;
            td.dataset.seatDesc = `${seat.row_name}${seat.seat_number} (${seat.category})`;
            
            // Handle Click
            td.onclick = () => {
                if (seat.status === "booked") return;
                // If held by others, return
                if (seat.status === "held" && !isSelfHeld) return;
                
                toggleSeatSelection(seat.seat_id, td);
            };
            
            tr.appendChild(td);
        });
        
        table.appendChild(tr);
    });
    
    container.appendChild(table);
    updateCheckoutPane();
}

function toggleSeatSelection(seatId, tdElement) {
    const price = parseFloat(tdElement.dataset.price);
    const desc = tdElement.dataset.seatDesc;

    // If already in active holds, we can't toggle select; they must release hold to edit
    if (activeHeldSeatIds.length > 0) {
        showAlert("You have an active seat hold. Confirm booking or cancel hold to make adjustments.", "warning");
        return;
    }

    if (selectedSeatIds.includes(seatId)) {
        selectedSeatIds = selectedSeatIds.filter(id => id !== seatId);
    } else {
        selectedSeatIds.push(seatId);
    }
    
    // Highlight elements visually
    if (selectedSeatIds.includes(seatId)) {
        tdElement.classList.remove("bg-indigo-200", "bg-sky-200", "hover:bg-indigo-300", "hover:bg-sky-300");
        tdElement.classList.add("bg-emerald-500", "border-emerald-600", "text-white");
    } else {
        tdElement.classList.remove("bg-emerald-500", "border-emerald-600", "text-white");
        const category = tdElement.dataset.category;
        if (category === "Premium") {
            tdElement.classList.add("bg-indigo-200", "border-indigo-300");
        } else {
            tdElement.classList.add("bg-sky-200", "border-sky-300");
        }
    }
    
    updateCheckoutPane();
}

function updateCheckoutPane() {
    const listContainer = document.getElementById("checkout-seats-list");
    listContainer.innerHTML = "";
    
    const count = selectedSeatIds.length || activeHeldSeatIds.length;
    document.getElementById("checkout-seats-count").innerText = count;
    
    let total = 0.0;
    const workingIds = activeHeldSeatIds.length > 0 ? activeHeldSeatIds : selectedSeatIds;
    
    if (workingIds.length === 0) {
        listContainer.innerHTML = `<p class="text-xs text-gray-400 italic">No seats selected</p>`;
    } else {
        workingIds.forEach(id => {
            const el = document.querySelector(`[data-seat-id="${id}"]`);
            if (el) {
                const desc = el.dataset.seatDesc;
                const price = parseFloat(el.dataset.price);
                total += price;
                
                const item = document.createElement("div");
                item.className = "flex justify-between text-xs";
                item.innerHTML = `<span>Seat ${desc}</span><strong>$${price.toFixed(2)}</strong>`;
                listContainer.appendChild(item);
            }
        });
    }
    
    document.getElementById("checkout-total-price").innerText = `$${total.toFixed(2)}`;
}

// WebSockets for Realtime updates
function connectWebSocket(eventId, pricing) {
    if (seatMapWebSocket) {
        seatMapWebSocket.close();
    }
    
    // Construct WebSocket URL matching backend endpoint
    const wsProto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${wsProto}//${window.location.host}/api/ws/events/${eventId}`;
    
    seatMapWebSocket = new WebSocket(wsUrl);
    
    seatMapWebSocket.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === "seat_update") {
            // Apply updates dynamically without resetting local select state
            data.seats.forEach(updatedSeat => {
                const el = document.querySelector(`[data-seat-id="${updatedSeat.seat_id}"]`);
                if (el) {
                    // Update dataset and styling
                    el.dataset.status = updatedSeat.status;
                    
                    const isSelected = selectedSeatIds.includes(updatedSeat.seat_id);
                    const isSelfHeld = activeHeldSeatIds.includes(updatedSeat.seat_id);
                    
                    // Reset styling classes
                    el.className = "w-9 h-9 border rounded-md text-xs font-semibold flex items-center justify-center cursor-pointer transition shadow-sm";
                    
                    if (isSelected) {
                        el.classList.add("bg-emerald-500", "border-emerald-600", "text-white");
                    } else if (isSelfHeld) {
                        el.classList.add("bg-emerald-600", "border-emerald-700", "text-white", "font-bold", "animate-pulse");
                    } else if (updatedSeat.status === "held") {
                        el.classList.add("bg-amber-400", "border-amber-500", "cursor-not-allowed");
                    } else if (updatedSeat.status === "booked") {
                        el.classList.add("bg-rose-500", "border-rose-600", "cursor-not-allowed", "text-white");
                    } else {
                        // available
                        if (updatedSeat.category === "Premium") {
                            el.classList.add("bg-indigo-200", "border-indigo-300", "hover:bg-indigo-300");
                        } else {
                            el.classList.add("bg-sky-200", "border-sky-300", "hover:bg-sky-300");
                        }
                    }
                }
            });
            updateCheckoutPane();
        }
    };
    
    seatMapWebSocket.onerror = (err) => {
        console.error("WebSocket error:", err);
    };
}

// Seat holding mechanics
async function holdSelectedSeats() {
    if (selectedSeatIds.length === 0) {
        showAlert("Please select at least one seat to place a hold", "warning");
        return;
    }
    
    try {
        const response = await fetchWithAuth(`${API_BASE}/events/${seatMapEventId}/hold`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ seat_ids: selectedSeatIds })
        });
        
        if (response.ok) {
            const heldSeats = await response.json();
            activeHeldSeatIds = heldSeats.map(s => s.seat_id);
            selectedSeatIds = []; // clear selection, they are now held
            
            // Set Timer
            const expires = parseUTCDate(heldSeats[0].expires_at);
            holdExpiresAt = expires;
            startHoldCountdown();
            
            // Update pane actions
            document.getElementById("btn-hold-seats").classList.add("hidden");
            document.getElementById("btn-book-seats").classList.remove("hidden");
            document.getElementById("btn-release-hold").classList.remove("hidden");
            document.getElementById("checkout-timer-panel").classList.remove("hidden");
            
            // Rerender seats to trigger holding colors
            heldSeats.forEach(hs => {
                const el = document.querySelector(`[data-seat-id="${hs.seat_id}"]`);
                if (el) {
                    el.className = "bg-emerald-600 border-emerald-700 text-white font-bold animate-pulse w-9 h-9 border rounded-md text-xs flex items-center justify-center cursor-pointer transition shadow-sm";
                }
            });
            
            updateCheckoutPane();
            showAlert("Seats held successfully! You have 10 minutes to complete checkout.", "success");
        } else {
            const error = await response.json();
            showAlert(error.detail || "Unable to hold seats", "error");
        }
    } catch (e) {
        showAlert("Connection error during seat hold.", "error");
    }
}

function startHoldCountdown() {
    clearInterval(holdTimerInterval);
    holdTimerInterval = setInterval(() => {
        const now = new Date();
        const diffMs = holdExpiresAt.getTime() - now.getTime();
        
        if (diffMs <= 0) {
            clearInterval(holdTimerInterval);
            showAlert("Seat hold expired. Seats have been released.", "warning");
            activeHeldSeatIds = [];
            // Refresh map
            openSeatMap(seatMapEventId);
            return;
        }
        
        const totalSecs = Math.floor(diffMs / 1000);
        const mins = Math.floor(totalSecs / 60);
        const secs = totalSecs % 60;
        
        document.getElementById("checkout-timer").innerText = `${mins}:${secs < 10 ? '0' : ''}${secs}`;
    }, 1000);
}

async function releaseActiveHolds() {
    if (activeHeldSeatIds.length === 0) return;
    
    try {
        const response = await fetchWithAuth(`${API_BASE}/events/${seatMapEventId}/release`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ seat_ids: activeHeldSeatIds })
        });
        
        if (response.ok) {
            activeHeldSeatIds = [];
            clearInterval(holdTimerInterval);
            showAlert("Holds released successfully.", "success");
            openSeatMap(seatMapEventId);
        } else {
            const error = await response.json();
            showAlert(error.detail || "Failed to release holds", "error");
        }
    } catch (e) {
        showAlert("Connection error releasing holds.", "error");
    }
}

async function bookHeldSeats() {
    if (activeHeldSeatIds.length === 0) return;
    
    try {
        const response = await fetchWithAuth(`${API_BASE}/events/${seatMapEventId}/book`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ seat_ids: activeHeldSeatIds })
        });
        
        if (response.ok) {
            const res = await response.json();
            clearInterval(holdTimerInterval);
            activeHeldSeatIds = [];
            
            showAlert(`Tickets Booked! Booking Ref: ${res.booking_reference}. Confirmation email generated in mail_spool.`, "success");
            navigate("my-bookings");
        } else {
            const error = await response.json();
            showAlert(error.detail || "Booking failed", "error");
        }
    } catch (e) {
        showAlert("Connection error during booking confirm.", "error");
    }
}

async function joinWaitlist() {
    const category = document.getElementById("waitlist-category").value;
    if (!category) return;
    
    try {
        const response = await fetchWithAuth(`${API_BASE}/events/${seatMapEventId}/waitlist`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ seat_category: category })
        });
        
        if (response.ok) {
            const price = document.getElementById("waitlist-price").innerText;
            showAlert(`Successfully joined waitlist for ${category}! Upfront payment of ${price} has been captured. If a seat frees up, it will be automatically booked for you.`, "success");
        } else {
            const error = await response.json();
            showAlert(error.detail || "Failed to join waitlist", "error");
        }
    } catch (e) {
        showAlert("Connection error joining waitlist.", "error");
    }
}

// ----------------- CUSTOMER: BOOKINGS HISTORY -----------------
async function loadCustomerBookings() {
    try {
        const response = await fetchWithAuth(`${API_BASE}/customer/bookings`);
        if (!response.ok) return;
        const bookings = await response.json();
        
        const container = document.getElementById("bookings-container");
        container.innerHTML = "";
        
        if (bookings.length === 0) {
            container.innerHTML = `<p class="text-center text-gray-500 py-10">You have no booking records.</p>`;
            return;
        }
        
        bookings.forEach(bk => {
            const isConfirmed = bk.status === "confirmed";
            
            const card = document.createElement("div");
            card.className = "bg-white p-6 rounded-lg shadow-sm border border-gray-100 flex flex-col md:flex-row justify-between items-start md:items-center gap-4";
            card.innerHTML = `
                <div class="space-y-2">
                    <div class="flex items-center space-x-2">
                        <span class="text-xs font-bold uppercase px-2 py-0.5 rounded ${isConfirmed ? 'bg-emerald-100 text-emerald-800' : 'bg-gray-100 text-gray-500'}">
                            ${bk.status}
                        </span>
                        <span class="text-sm font-semibold text-gray-500">Ref: ${bk.booking_reference}</span>
                    </div>
                    <h3 class="text-xl font-bold text-gray-900">${bk.event_title}</h3>
                    <p class="text-xs text-gray-500">${bk.event_date} at ${bk.event_time}</p>
                    <p class="text-sm text-gray-700"><strong>Seats:</strong> ${bk.seats.join(", ")}</p>
                </div>
                <div class="text-left md:text-right space-y-2 w-full md:w-auto flex md:flex-col justify-between items-center md:items-end">
                    <div>
                        <span class="block text-xs text-gray-400">Paid Amount</span>
                        <span class="text-lg font-extrabold text-indigo-600">$${bk.price_paid.toFixed(2)}</span>
                    </div>
                    ${isConfirmed ? `
                        <button onclick="cancelBooking('${bk.booking_reference}')" class="bg-rose-50 text-rose-600 px-3 py-1.5 rounded text-xs font-bold hover:bg-rose-100 border border-rose-200 transition">
                            Cancel Order
                        </button>
                    ` : ""}
                </div>
            `;
            container.appendChild(card);
        });
    } catch (e) {
        console.error("Error loading customer bookings:", e);
    }
}

async function cancelBooking(bookingRef) {
    if (!confirm("Are you sure you want to cancel this booking? Held waitlist offers will automatically trigger for these seats.")) return;
    
    try {
        const response = await fetchWithAuth(`${API_BASE}/bookings/${bookingRef}/cancel`, {
            method: "POST"
        });
        
        if (response.ok) {
            showAlert("Booking cancelled successfully.", "success");
            loadCustomerBookings();
        } else {
            const error = await response.json();
            showAlert(error.detail || "Cancellation failed", "error");
        }
    } catch (e) {
        showAlert("Connection error during cancellation", "error");
    }
}

// ----------------- CLAIM WAITLIST OFFER PAGE -----------------
let claimOfferId = null;

async function loadOfferPage(offerId) {
    if (!currentUser) {
        showAlert("Please log in to claim a waitlist offer.", "error");
        // Store URL so user is redirected back
        navigate("login");
        return;
    }
    
    claimOfferId = offerId;
    
    try {
        const response = await fetch(`${API_BASE}/offers/${offerId}`);
        if (!response.ok) throw new Error("Offer not found or expired");
        
        const offer = await response.json();
        const card = document.getElementById("offer-details-card");
        
        if (offer.expired) {
            card.innerHTML = `<p class="text-rose-600 font-semibold text-center py-4">This offer is no longer valid or has expired.</p>`;
            document.getElementById("offer-actions").classList.add("hidden");
            navigate("claim-offer");
            return;
        }
        
        // Show offer details and start expiration countdown
        document.getElementById("offer-actions").classList.remove("hidden");
        
        card.innerHTML = `
            <div class="space-y-2 text-sm text-gray-700">
                <p><strong>Event:</strong> ${offer.event_title}</p>
                <p><strong>Category:</strong> ${offer.seat_category}</p>
                <p><strong>Seat Number:</strong> ${offer.seat_desc}</p>
                <p><strong>Price:</strong> <span class="text-amber-700 font-bold">$${offer.price.toFixed(2)}</span></p>
                <div class="p-2.5 bg-amber-100 rounded text-amber-900 mt-4 flex justify-between font-semibold">
                    <span>Expiring in:</span>
                    <span id="offer-countdown" class="font-extrabold text-base"></span>
                </div>
            </div>
        `;
        
        const expires = parseUTCDate(offer.expires_at);
        startOfferCountdown(expires);
        
        navigate("claim-offer");
    } catch (e) {
        showAlert(e.message, "error");
        navigate("events");
    }
}

function startOfferCountdown(expiresAt) {
    clearInterval(holdTimerInterval);
    holdTimerInterval = setInterval(() => {
        const now = new Date();
        const diffMs = expiresAt.getTime() - now.getTime();
        
        if (diffMs <= 0) {
            clearInterval(holdTimerInterval);
            document.getElementById("offer-details-card").innerHTML = `<p class="text-rose-600 font-semibold text-center py-4">This offer has expired.</p>`;
            document.getElementById("offer-actions").classList.add("hidden");
            return;
        }
        
        const totalSecs = Math.floor(diffMs / 1000);
        const mins = Math.floor(totalSecs / 60);
        const secs = totalSecs % 60;
        
        const countdownEl = document.getElementById("offer-countdown");
        if (countdownEl) {
            countdownEl.innerText = `${mins}:${secs < 10 ? '0' : ''}${secs}`;
        }
    }, 1000);
}

async function claimOffer() {
    if (!claimOfferId) return;
    
    try {
        const response = await fetchWithAuth(`${API_BASE}/offers/${claimOfferId}/claim`, {
            method: "POST"
        });
        
        if (response.ok) {
            const data = await response.json();
            clearInterval(holdTimerInterval);
            showAlert(`Ticket purchased! Booking reference: ${data.booking_reference}`, "success");
            window.location.hash = ""; // Clear hash
            navigate("my-bookings");
        } else {
            const error = await response.json();
            showAlert(error.detail || "Claim failed", "error");
        }
    } catch (e) {
        showAlert("Error claiming offer.", "error");
    }
}

// ----------------- ORGANISER DASHBOARD -----------------
async function loadOrganiserDashboard() {
    // Load venues for selector
    try {
        const venRes = await fetchWithAuth(`${API_BASE}/admin/venues`);
        if (venRes.ok) {
            const venues = await venRes.json();
            const sel = document.getElementById("event-venue");
            sel.innerHTML = "";
            venues.forEach(v => {
                const opt = document.createElement("option");
                opt.value = v.id;
                opt.innerText = `${v.name} (Capacity: ${v.total_seats})`;
                sel.appendChild(opt);
            });
        }
        
        // Load organiser event summaries
        const listRes = await fetchWithAuth(`${API_BASE}/organiser/events`);
        if (!listRes.ok) return;
        const events = await listRes.json();
        
        const listContainer = document.getElementById("organiser-listings-container");
        listContainer.innerHTML = "";
        
        if (events.length === 0) {
            listContainer.innerHTML = `<p class="text-center text-gray-500 py-6">You have created no event listings.</p>`;
            return;
        }
        
        events.forEach(async (ev) => {
            const card = document.createElement("div");
            card.className = "bg-white p-5 rounded-lg shadow-sm border border-gray-100 space-y-4";
            card.id = `organiser-event-${ev.id}`;
            card.innerHTML = `
                <div class="flex justify-between items-center border-b pb-2">
                    <div>
                        <h4 class="text-lg font-bold text-gray-900">${ev.title}</h4>
                        <span class="text-xs text-gray-500">${ev.date} at ${ev.time}</span>
                    </div>
                    <span class="text-xs bg-indigo-50 text-indigo-700 font-bold px-2 py-0.5 rounded">ID: ${ev.id}</span>
                </div>
                <div class="grid grid-cols-2 md:grid-cols-4 gap-4 text-center">
                    <div>
                        <span class="block text-xs text-gray-400">Bookings</span>
                        <span id="stat-bookings-${ev.id}" class="text-lg font-extrabold text-gray-800">--</span>
                    </div>
                    <div>
                        <span class="block text-xs text-gray-400">Cancelled</span>
                        <span id="stat-cancelled-${ev.id}" class="text-lg font-extrabold text-gray-500">--</span>
                    </div>
                    <div>
                        <span class="block text-xs text-gray-400">Waitlist Size</span>
                        <span id="stat-waitlist-${ev.id}" class="text-lg font-extrabold text-amber-600">--</span>
                    </div>
                    <div>
                        <span class="block text-xs text-gray-400">Total Revenue</span>
                        <span id="stat-revenue-${ev.id}" class="text-lg font-extrabold text-indigo-600">--</span>
                    </div>
                </div>
            `;
            listContainer.appendChild(card);
            
            // Lazy load revenues
            try {
                const sumRes = await fetchWithAuth(`${API_BASE}/organiser/events/${ev.id}/summary`);
                if (sumRes.ok) {
                    const stats = await sumRes.json();
                    document.getElementById(`stat-bookings-${ev.id}`).innerText = stats.total_bookings;
                    document.getElementById(`stat-cancelled-${ev.id}`).innerText = stats.cancelled_bookings;
                    document.getElementById(`stat-waitlist-${ev.id}`).innerText = stats.waitlist_count;
                    document.getElementById(`stat-revenue-${ev.id}`).innerText = `$${stats.total_revenue.toFixed(2)}`;
                }
            } catch (e) {
                console.error("Err stats loading:", e);
            }
        });
    } catch (e) {
        console.error("Err organiser dash:", e);
    }
}

async function handleCreateEvent(e) {
    e.preventDefault();
    const title = document.getElementById("event-title").value;
    const description = document.getElementById("event-desc").value;
    const date = document.getElementById("event-date").value;
    const time = document.getElementById("event-time").value;
    const venue_id = parseInt(document.getElementById("event-venue").value);
    
    const premium_price = parseFloat(document.getElementById("price-premium").value);
    const standard_price = parseFloat(document.getElementById("price-standard").value);
    const pricing = {
        "Premium": premium_price,
        "Standard": standard_price
    };
    
    try {
        const response = await fetchWithAuth(`${API_BASE}/organiser/events`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ title, description, date, time, venue_id, pricing })
        });
        
        if (response.ok) {
            showAlert("Event listing created and seats generated!", "success");
            // Clear fields
            document.getElementById("event-title").value = "";
            document.getElementById("event-desc").value = "";
            loadOrganiserDashboard();
        } else {
            const error = await response.json();
            showAlert(error.detail || "Event creation failed", "error");
        }
    } catch (e) {
        showAlert("Error publishing event.", "error");
    }
}

// ----------------- ADMIN DASHBOARD -----------------
async function loadAdminDashboard() {
    try {
        const response = await fetchWithAuth(`${API_BASE}/admin/venues`);
        if (!response.ok) return;
        
        const venues = await response.json();
        const container = document.getElementById("venues-list-container");
        container.innerHTML = "";
        
        if (venues.length === 0) {
            container.innerHTML = `<p class="col-span-full text-center text-gray-500 py-6">No venues configured.</p>`;
            return;
        }
        
        venues.forEach(v => {
            const layout = JSON.parse(v.layout);
            const card = document.createElement("div");
            card.className = "bg-white p-5 rounded-lg shadow-sm border border-gray-100 space-y-2";
            card.innerHTML = `
                <h4 class="text-lg font-bold text-indigo-700">${v.name}</h4>
                <p class="text-sm text-gray-500">${v.address}</p>
                <div class="border-t pt-2 mt-2 text-xs text-gray-400 space-y-1">
                    <p><strong>Capacity:</strong> ${v.total_seats} seats</p>
                    <p><strong>Layout:</strong> Rows ${layout.rows.join(",")} (Seats/Row: ${layout.seats_per_row})</p>
                </div>
            `;
            container.appendChild(card);
        });
    } catch (e) {
        console.error("Admin error loading venues:", e);
    }
}

async function handleCreateVenue(e) {
    e.preventDefault();
    const name = document.getElementById("venue-name").value;
    const address = document.getElementById("venue-address").value;
    
    // Parse layout properties
    const rowsRaw = document.getElementById("venue-rows").value;
    const seatsPerRow = parseInt(document.getElementById("venue-seats-row").value);
    const premiumRowsRaw = document.getElementById("venue-premium-rows").value;
    
    const rows = rowsRaw.split(",").map(r => r.trim().toUpperCase()).filter(Boolean);
    const premiumRows = premiumRowsRaw.split(",").map(r => r.trim().toUpperCase()).filter(Boolean);
    
    // Create category map
    const category_map = {};
    rows.forEach(r => {
        category_map[r] = premiumRows.includes(r) ? "Premium" : "Standard";
    });
    
    const layout = {
        rows: rows,
        seats_per_row: seatsPerRow,
        category_map: category_map
    };
    
    try {
        const response = await fetchWithAuth(`${API_BASE}/admin/venues`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name, address, layout })
        });
        
        if (response.ok) {
            showAlert("Venue created successfully!", "success");
            // Clear inputs
            document.getElementById("venue-name").value = "";
            document.getElementById("venue-address").value = "";
            loadAdminDashboard();
        } else {
            const error = await response.json();
            showAlert(error.detail || "Venue creation failed", "error");
        }
    } catch (e) {
        showAlert("Error publishing venue.", "error");
    }
}

// ----------------- GLOBAL BANNER ALERT -----------------
function showAlert(text, type = "info") {
    const banner = document.getElementById("alert-banner");
    const txt = document.getElementById("alert-text");
    
    txt.innerText = text;
    banner.className = "mb-6 p-4 rounded-md shadow-sm flex items-center justify-between transition duration-200 animate-bounce";
    
    if (type === "success") {
        banner.classList.add("bg-emerald-50", "border", "border-emerald-200", "text-emerald-800");
    } else if (type === "error") {
        banner.classList.add("bg-rose-50", "border", "border-rose-200", "text-rose-800");
    } else if (type === "warning") {
        banner.classList.add("bg-amber-50", "border", "border-amber-200", "text-amber-800");
    } else {
        banner.classList.add("bg-indigo-50", "border", "border-indigo-200", "text-indigo-800");
    }
    
    banner.classList.remove("hidden");
    
    // Auto close after 6 seconds
    setTimeout(() => {
        closeAlert();
    }, 6000);
}

function closeAlert() {
    const banner = document.getElementById("alert-banner");
    banner.classList.add("hidden");
}
