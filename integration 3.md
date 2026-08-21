# Navigatto AI Assistant - Frontend Integration Guide


## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Base URLs](#base-urls)
4. [Authentication](#authentication)
5. [WebSocket Connection](#websocket-connection)
6. [Chat Messaging](#chat-messaging)
7. [Thread Management APIs](#thread-management-apis)
8. [Cache Management API](#cache-management-api)
9. [CSV Export API](#csv-export-api)
10. [Complete Integration Example](#complete-integration-example)
11. [Error Handling](#error-handling)
12. [Best Practices](#best-practices)

---

## Overview

The Navigatto AI Assistant provides a conversational interface for fleet management data.

### 🔑 Authentication Model

**CRITICAL**: This backend does **NOT** handle user login or authentication.

- ❌ **No login endpoint**
- ❌ **No password verification**
- ❌ **No user registration**

**Only JWT verification:**
1. User authenticates with **YOUR system**
2. Your system issues **JWT with UserId**
3. Frontend sends **JWT to our backend**
4. Backend **verifies JWT** and does everything else automatically

**That's it. Simple and secure.**

---

### Core Capabilities
- **JWT-Only Authentication**: Only verifies JWT signature and extracts UserId
- **Automatic Tenant Resolution**: Backend resolves tenant from UserId
- **Multi-Tenant Architecture**: Isolated data per tenant
- **Real-Time Chat**: WebSocket-based streaming responses
- **Thread History**: Persistent conversation management
- **RBAC Filtering**: User-specific data access control
- **Audit Logging**: Complete tracking of queries and usage

### Key Features
- ✅ **Zero authentication overhead** - Use your existing auth system
- ✅ **Seamless integration** - Just send JWT token
- ✅ Streaming AI responses with token-by-token delivery
- ✅ Automatic thread creation with smart titles
- ✅ Thread history with delete functionality
- ✅ CSV export for complete datasets
- ✅ Automatic RBAC filtering on all queries
- ✅ Audit and usage tracking for compliance

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    PRODUCTION FLOW                        │
└──────────────────────────────────────────────────────────┘

┌─────────────┐
│  Frontend   │  (Receives JWT from your auth system)
└──────┬──────┘
       │
       │ 1. Send JWT Only
       │    Headers: Authorization: Bearer <JWT>
       │    JWT contains: {UserId}
       │
       │ 2. Connect WebSocket
       │    auth: {token: JWT}
       ├──────────────────────────────────────────────┐
       │                                              │
       │ 3. Backend Internal Flow:                    │
       │    ┌─────────────────────────────────────┐  │
       │    │ a) Verify JWT (your JWT verifier)  │  │
       │    │ b) Extract UserId from JWT         │  │
       │    │ c) Query AspNetUsers by UserId     │  │
       │    │ d) Get CustomerId from AspNetUsers │  │
       │    │ e) Resolve Tenant DB from UserId   │  │
       │    │ f) Load RBAC Context               │  │
       │    │ g) Establish Connection            │  │
       │    └─────────────────────────────────────┘  │
       │◄──────────────────────────────────────────────┘
       │
       │ 4. Emit: chat_message
       │    {message, thread_id}
       ├──────────────────────────────────────────────┐
       │                                              │
       │ 5. Receive Events:                           │
       │    - chat:start {thread_id}                  │
       │    - chat:token {content}                    │
       │    - chat:data {results}                     │
       │    - chat:done                               │
       │◄──────────────────────────────────────────────┘
       │
       │ 6. GET /api/threads/
       │    Headers: Authorization: Bearer <JWT>
       ├──────────────────────────────────────────────┐
       │                                              │
       │ 7. Backend:                                  │
       │    - Extract UserId from JWT                 │
       │    - Get CustomerId from AspNetUsers         │
       │    - Return user's threads                   │
       │                                              │
       │ 8. Response: [{id, title, ...}]              │
       │◄──────────────────────────────────────────────┘
```

### AI Pipeline (backend — for context)

Each `chat_message` runs through a layered agentic pipeline. You don't call these directly, but the `agent_status` progress events map to them:

- **Layer 0 — guards:** rejects oversized input (`MAX_INPUT_CHARS`) and raw SQL pasted as a "question".
- **Layer 1 — intent router + SP selector:** handles greetings/small-talk directly, selects the right stored procedure, and **rephrases follow-ups** ("show them by mode") into standalone questions using conversation memory.
- **Layer 2 — parameter resolution:** resolves names → IDs (the user never provides IDs), fills dates, and asks a friendly clarifying question only when needed. Pending clarifications and partial answers are remembered across turns.
- **Layer 3 — execution + recovery:** runs the SP/SQL; on failure it rebuilds an equivalent query from the SP's real definition, else falls back to generated SQL, else replies "no relevant information found."

Server-side RBAC (customer/asset/driver isolation) is always injected regardless of what the model produces.

---

## Base URLs

### Development
```
HTTP:  http://localhost:8000
WS:    ws://localhost:8000
```

### Production
```
HTTP:  https://your-api-domain.com
WS:    wss://your-api-domain.com
```

---

## Authentication

### How It Works

**IMPORTANT**: The Navigatto AI backend does **NOT** handle user authentication or login. You manage authentication in your own system.

**Simple Flow**:
1. User logs into **YOUR authentication system**
2. Your system issues a **JWT token** containing `UserId`
3. Frontend sends **JWT token** to Navigatto AI backend
4. Backend **verifies JWT** and extracts `UserId`
5. Backend handles everything else automatically

**No login endpoint. No password verification. Only JWT verification.**

---

### JWT Requirements

Your JWT **must** contain:
```json
{
  "user_id": "58bc8c36-c29c-463c-ba9a-f175676379a7",  // REQUIRED: User's GUID
  "email": "user@example.com",                       // Optional
  "exp": 1234567890                                   // REQUIRED: Expiration
}
```

**That's it!** The backend does the rest.

---

### What Backend Does Automatically

When you send a JWT, the backend:

1. ✅ **Verifies JWT** signature and expiration
2. ✅ **Extracts `UserId`** from JWT payload
3. ✅ **Queries `AspNetUsers`**: `SELECT CustomerId, IsSuperUser FROM AspNetUsers WHERE Id = '{UserId}'`
4. ✅ **Gets `CustomerId`** from the result
5. ✅ **Resolves Tenant Database** using UserId (internal mapping)
6. ✅ **Loads RBAC Context** (permissions, allowed assets/drivers)
7. ✅ **Establishes Connection** with full user context

**You manage**: User authentication, JWT issuance  
**Backend manages**: Everything else (tenant resolution, RBAC, database connections)

---

### What You Send

✅ **Send**:
- JWT token (contains `UserId`)

❌ **Don't Send**:
- Passwords
- Domain/tenant information
- CustomerId
- Login credentials
- Any tenant-specific data

---

### Store JWT Token

```javascript
// After user logs into YOUR system and you get JWT
const jwtToken = yourAuthSystem.getToken();

// Store it
localStorage.setItem('access_token', jwtToken);

// Optional: Store user info for UI display
localStorage.setItem('user_id', userId);
localStorage.setItem('user_email', userEmail);
```

---

## WebSocket Connection

### Install Socket.IO Client

```bash
npm install socket.io-client
```

### Establish Connection

**Production**: Only send JWT token, backend handles all tenant resolution.

```javascript
import { io } from "socket.io-client";

const accessToken = localStorage.getItem('access_token');

const socket = io("http://localhost:8000", {
    path: "/socket.io/",
    auth: {
        token: accessToken  // Only JWT required - contains UserId
    },
    transports: ["websocket"],
    reconnection: true,
    reconnectionAttempts: 10,
    reconnectionDelay: 1000,
    reconnectionDelayMax: 5000
});
```

**What the backend does internally**:
1. Receives JWT from `auth.token`
2. Verifies JWT and extracts `UserId`
3. Queries `AspNetUsers` to get `CustomerId`
4. Resolves tenant database from `UserId`
5. Loads RBAC context
6. Establishes connection

### Connection Events

```javascript
// Successfully connected
socket.on("connect", () => {
    console.log("✅ Connected to AI Assistant");
    console.log("Socket ID:", socket.id);
});

// Disconnected
socket.on("disconnect", (reason) => {
    console.log("❌ Disconnected:", reason);
});

// Connection error
socket.on("connect_error", (error) => {
    console.error("Connection failed:", error.message);
    // Common errors:
    // - "Invalid token"
    // - "Tenant resolution failed"
    // - "RBAC loading failed"
});

// Reconnecting
socket.on("reconnect_attempt", (attemptNumber) => {
    console.log(`Reconnecting... Attempt ${attemptNumber}`);
});

// Reconnected
socket.on("reconnect", (attemptNumber) => {
    console.log(`✅ Reconnected after ${attemptNumber} attempts`);
});
```

### Backend Authentication Flow

When you connect, the backend automatically:

1. **Extracts JWT** from `auth.token`
2. **Verifies JWT** using your JWT verification system
3. **Extracts `UserId`** from JWT payload
4. **Queries `AspNetUsers`** table: `SELECT CustomerId, IsSuperUser FROM AspNetUsers WHERE Id = '{UserId}'`
5. **Gets `CustomerId`** from the result
6. **Resolves tenant database** using the `UserId` (internal tenant mapping)
7. **Connects to tenant database** using resolved credentials
8. **Loads RBAC context** for the user (CustomerId, IsSuperUser, allowed assets/drivers)
9. **Establishes connection** and stores context for this session

All subsequent messages are automatically filtered by this user's RBAC permissions.

**You don't manage**: Tenant resolution, CustomerId lookup, RBAC loading  
**Backend handles**: Everything automatically from the UserId in your JWT

---

## Chat Messaging

### Send Message

**Event**: `chat_message`

```javascript
socket.emit("chat_message", {
    message: "Show me top performing drivers this month",
    thread_id: currentThreadId  // null for new conversation
});
```

**Parameters**:
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `message` | string | ✅ Yes | User's query or prompt |
| `thread_id` | string (UUID) | ❌ No | Existing conversation thread ID. Omit or set to `null` for new conversation |

### Receive Events

#### 1. `chat:start` - Processing Started

Emitted when the backend starts processing your message.

```javascript
socket.on("chat:start", (data) => {
    console.log("Thread ID:", data.thread_id);
    currentThreadId = data.thread_id;    // Save for next message
    currentRequestId = data.request_id;  // Save to allow Stop (see chat_stop)

    // UI Actions:
    // - Save thread ID + request ID
    // - Create assistant message container
    // - Show loading animation (and a Stop button)
});
```

**Payload**:
```json
{
  "thread_id": "98e7bd50-582a-4be7-bd8f-a12cea64cb8a",
  "request_id": "b1f0c2e4-9a77-4c1e-9d2a-2f0b5d6e8a10"
}
```

> `request_id` is new. Echo it back in `chat_stop` to cancel this specific in-flight request.

#### 2. `chat:token` - Streaming Response

AI response is streamed token-by-token for real-time display.

```javascript
let assistantMessage = "";

socket.on("chat:token", (data) => {
    assistantMessage += data.content;
    
    // Update UI in real-time
    document.getElementById('ai-response').textContent = assistantMessage;
});
```

**Payload**:
```json
{
  "content": "Here"
}
```

**Important**: Do NOT wait for `chat:done`. Render tokens immediately as they arrive for a smooth streaming experience.

#### 3. `chat:data` - Structured Data

Used for charts, tables, maps, and other structured responses.

```javascript
socket.on("chat:data", (data) => {
    if (data.event === "sql") {
        console.log("Generated SQL:", data.sql);
    }
    
    if (data.event === "results") {
        console.log("Columns:", data.columns);
        console.log("Rows:", data.rows);
        console.log("Total:", data.total_rows);
        
        // Render table or chart
        renderChart(data);
    }
    
    if (data.event === "suggestions") {
        console.log("Follow-up questions:", data.suggestions);
        // Display suggestion chips
    }
});
```

**Results Payload**:
```json
{
  "event": "results",
  "columns": ["DriverName", "TotalDistance", "HarshEvents"],
  "rows": [
    {
      "DriverName": "John Doe",
      "TotalDistance": 1250.5,
      "HarshEvents": 3
    },
    {
      "DriverName": "Jane Smith",
      "TotalDistance": 980.2,
      "HarshEvents": 1
    }
  ],
  "total_rows": 150,
  "shown_rows": 2,
  "is_aggregate": true,
  "sql": "SELECT DriverName, SUM(Distance) as TotalDistance..."
}
```

**SQL Event Payload**:
```json
{
  "event": "sql",
  "sql": "SELECT TOP 10 d.DriverName, SUM(aj.JourneyDistanceTravelled) as TotalDistance FROM Driver d JOIN AssetJourney aj ON d.DriverId = aj.DriverId WHERE d.CustomerId = 376 GROUP BY d.DriverName ORDER BY TotalDistance DESC"
}
```

**Suggestions Payload**:
```json
{
  "event": "suggestions",
  "suggestions": [
    "Show drivers with most harsh events",
    "Compare fuel efficiency by driver",
    "Show idle time by driver"
  ]
}
```

**Visualization Metadata** (Optional):
```json
{
  "event": "results",
  "visualization": {
    "type": "bar",
    "config": {
      "labelColumn": "DriverName",
      "valueColumn": "TotalDistance",
      "title": "Top Drivers by Distance"
    }
  },
  "columns": [...],
  "rows": [...]
}
```

**Supported Visualization Types**:
- `bar` - Bar chart
- `pie` - Pie chart
- `line` - Line/time-series chart
- `map` - GPS map with markers
- `kpi` - KPI cards
- `table` - Data table (default)

**Agent Progress Payload** (`event: "agent_status"`) — *optional*:

Live progress of the backend pipeline, so you can show *where* processing has reached instead of a static spinner. Arrives as `chat:data` with `event: "agent_status"`.

```javascript
socket.on("chat:data", (data) => {
    if (data.event === "agent_status") {
        // data.stage: understanding | reading_schema | selecting | thinking |
        //             resolving | executing | recovering
        // data.sp:    (optional) the stored procedure being used
        updateProgress(data.stage, data.sp);
        return;   // keep the loader visible; not a final result
    }
    // ... results / sql / suggestions handling ...
});
```
```json
{ "event": "agent_status", "stage": "executing", "sp": "sp_GetAssetJourneys" }
```

> **Controlled by the backend flag `EMIT_AGENT_STATUS`** (`.env`). When `false` (production default may be off), these events are simply never sent — your handler above is harmless either way. Treat it as **optional**: the app must work whether or not the events arrive.

#### 4. `chat:error` - Error Occurred

```javascript
socket.on("chat:error", (data) => {
    console.error("Error:", data.message);
    
    // UI Actions:
    // - Display error message
    // - Stop loading animation
    // - Re-enable input
});
```

**Payload**:
```json
{
  "message": "I encountered an error generating the query. Please try again."
}
```

**Common Errors**:
- `"Not authenticated"` - Invalid or expired JWT
- `"Message cannot be empty"` - Empty message sent
- `"Message too long (max 2000 characters)..."` - Input exceeds the backend length limit (`MAX_INPUT_CHARS`, default 2000). The backend rejects it before any processing; enforce the same cap client-side (`maxlength`).
- `"Processing failed: ..."` - Backend processing error
- `"I couldn't identify relevant tables for your query"` - Query too vague

#### 5. `chat:done` - Processing Complete

```javascript
socket.on("chat:done", () => {
    console.log("✅ Response complete");
    
    // UI Actions:
    // - Stop loading animation
    // - Enable message input
    // - Mark response as complete
    // - Reload thread history (optional)
});
```

**Payload**: Empty object `{}`

### Stop / Cancel a Request

Cancel an in-flight request (Stop button). Cancellation is **cooperative** — the backend stops the pipeline at the next stage boundary (it never hard-kills a running DB query), then confirms. A user can only stop their **own** connection's requests.

**Send event**: `chat_stop`
```javascript
function stopRequest() {
    socket.emit("chat_stop", {
        request_id: currentRequestId,   // from chat:start (optional)
        thread_id: currentThreadId      // optional
    });
}
```
> If `request_id` is omitted, the backend stops whatever is currently running for your connection.

**Receive events**:

`chat:stopping` — acknowledgment that the stop was received:
```javascript
socket.on("chat:stopping", (data) => { /* show "Stopping…" */ });
```
`chat:stopped` — the request was cancelled; reset the UI (re-enable input, keep any partial text):
```javascript
socket.on("chat:stopped", (data) => {
    // data: { request_id, thread_id }
    enableInput();
});
```

---

## Thread Management APIs

### Get All Threads

Retrieve conversation history for the authenticated user.

**Endpoint**: `GET /api/threads/`

**Headers**:
```http
Authorization: Bearer {access_token}
```

**Note**: Only JWT required. Backend extracts UserId from JWT and resolves tenant automatically.

**Query Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | integer | 50 | Maximum threads to return |
| `offset` | integer | 0 | Pagination offset |

**Request Example**:
```javascript
const accessToken = localStorage.getItem('access_token');

const response = await fetch('http://localhost:8000/api/threads/', {
    headers: {
        'Authorization': `Bearer ${accessToken}`
    }
});

const threads = await response.json();
```

**Success Response** (200 OK):
```json
[
  {
    "id": "98e7bd50-582a-4be7-bd8f-a12cea64cb8a",
    "title": "Show me top performing drivers this month",
    "created_at": "2026-06-16T10:57:43.724000",
    "updated_at": "2026-06-16T10:58:12.156000",
    "message_count": 4
  },
  {
    "id": "7a3f2c1d-9b8e-4f5a-a1c3-d4e5f6a7b8c9",
    "title": "Which vehicles have high fuel consumption?",
    "created_at": "2026-06-16T09:30:15.234000",
    "updated_at": "2026-06-16T09:35:42.891000",
    "message_count": 6
  }
]
```

**Error Responses**:
```json
// 401 Unauthorized
{
  "detail": "Authorization header missing"
}

// 400 Bad Request
{
  "detail": "Invalid JWT token"
}

// 404 Not Found
{
  "detail": "User not found or has no CustomerId"
}
```

### Get Thread Messages

Retrieve all messages in a specific conversation thread.

**Endpoint**: `GET /api/threads/{thread_id}/messages`

**Headers**:
```http
Authorization: Bearer {access_token}
```

**Note**: Backend extracts UserId from JWT and resolves tenant automatically.

**Query Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | integer | 100 | Maximum messages to return |
| `offset` | integer | 0 | Pagination offset |

**Request Example**:
```javascript
const threadId = "98e7bd50-582a-4be7-bd8f-a12cea64cb8a";

const response = await fetch(`http://localhost:8000/api/threads/${threadId}/messages`, {
    headers: {
        'Authorization': `Bearer ${accessToken}`
    }
});

const messages = await response.json();
```

**Success Response** (200 OK):
```json
[
  {
    "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "role": "user",
    "content": "Show me top performing drivers this month",
    "created_at": "2026-06-16T10:57:43.750000"
  },
  {
    "id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
    "role": "assistant",
    "content": "Here are the top performing drivers for this month based on distance traveled and safety metrics:\n\n1. John Doe - 1,250 km, 3 harsh events\n2. Jane Smith - 980 km, 1 harsh event\n...",
    "metadata": "{\"results\": {\"columns\": [\"DriverName\",\"TotalDistance\"], \"rows\": [...], \"total_rows\": 150, \"visualization\": {\"type\": \"bar\", \"config\": {...}}, \"is_aggregate\": true, \"sql\": \"...\"}}",
    "created_at": "2026-06-16T10:57:45.234000"
  }
]
```

**Chart / data history replay** — the new `metadata` field lets you **re-render past charts and tables** when a thread is reopened (previously only text came back):

- `metadata` is a **JSON string** (or `null`). When present on an `assistant` message, parse it and read `metadata.results` — it is the **same payload** as the live `chat:data` `results` event (`columns`, `rows`, `visualization`, `is_aggregate`, `total_rows`, `sql`).
- Feed it to the exact same renderer you use for live results:

```javascript
messages.forEach(msg => {
    const el = renderMessage(msg.role, msg.content);
    if (msg.role === "assistant" && msg.metadata) {
        try {
            const meta = JSON.parse(msg.metadata);
            if (meta.results) renderResultsInto(el, meta.results);  // same renderer as chat:data
        } catch (_) { /* ignore malformed metadata */ }
    }
});
```
> Only messages created **after** this feature shipped will have `metadata`; older messages return `null` and render as text only. The stored payload is the inline preview (≤10 rows); "Download Full Dataset" still re-runs the SQL via the CSV export API.

**Error Responses**:
```json
// 404 Not Found
{
  "detail": "Thread not found or not owned by user"
}

// 403 Forbidden
{
  "detail": "Access denied to this thread"
}
```

### Delete Thread

Delete a conversation thread and all its messages.

**Endpoint**: `DELETE /api/threads/{thread_id}`

**Headers**:
```http
Authorization: Bearer {access_token}
```

**Note**: Backend extracts UserId from JWT and resolves tenant automatically.

**Request Example**:
```javascript
const threadId = "98e7bd50-582a-4be7-bd8f-a12cea64cb8a";

const response = await fetch(`http://localhost:8000/api/threads/${threadId}`, {
    method: 'DELETE',
    headers: {
        'Authorization': `Bearer ${accessToken}`
    }
});

const result = await response.json();
```

**Success Response** (200 OK):
```json
{
  "message": "Thread deleted successfully",
  "thread_id": "98e7bd50-582a-4be7-bd8f-a12cea64cb8a"
}
```

**Error Responses**:
```json
// 404 Not Found
{
  "detail": "Thread not found or not owned by user"
}

// 403 Forbidden
{
  "detail": "Cannot delete thread owned by another user"
}
```

**Important**: Deleting a thread also deletes all associated messages due to CASCADE delete constraints.

---

## Cache Management API

Clear the cached data for the signed-in user's customer. Use it after the customer's
fleet/config changes (new vehicles, modes, groups, asset types, RBAC) so the next
question runs fresh queries instead of returning a stale cached answer — e.g. a
"Refresh data" button in your settings UI.

**Endpoint**: `POST /api/cache/clear`

**Headers**:
```http
Authorization: Bearer {access_token}
```

**No request body.** The customer is derived from the JWT — a user can **only** clear
their own customer's cache, never another customer's. (There is no `customer_id` to
send, and any client-supplied value would be ignored.) Tenant domain is resolved
automatically from the `Origin`/`Referer`/`Host` header, exactly like the thread APIs.

**What it clears** (Redis, scoped to this customer):
- **Query cache** (`qcache:<customerId>:*`) — previously cached answers/results.
- **Customer context** (`ctx:<customerId>`) — the groups/asset-types/modes/assets lookup the assistant loads per customer.

**Request Example**:
```javascript
const response = await fetch('http://localhost:8000/api/cache/clear', {
    method: 'POST',
    headers: {
        'Authorization': `Bearer ${accessToken}`
    }
});

const result = await response.json();
```

**cURL**:
```bash
curl -X POST http://localhost:8000/api/cache/clear \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

**Success Response** (200 OK):
```json
{
  "success": true,
  "customer_id": "376",
  "query_cache_cleared": 12,
  "customer_context_cleared": true,
  "message": "Cache cleared for customer 376"
}
```

**Error Responses**:
```json
// 401 Unauthorized
{
  "detail": "Authorization header missing or invalid"
}

// 404 Not Found
{
  "detail": "User {id} not found or has no CustomerId"
}
```

> **Admin note:** to flush another customer's cache from a backend/ops tool (also drops
> RBAC + tenant-domain caches), use `POST /api/admin/cache/flush` with an `Admin-Secret`
> header and `{ "customer_id": "..." }` in the body. That endpoint is **not** for the
> frontend — the JWT-based `/api/cache/clear` above is what your app should call.

---

## CSV Export API

Export complete datasets as CSV files.

**Endpoint**: `POST /api/export/csv`

**Headers**:
```http
Authorization: Bearer {access_token}
Content-Type: application/json
```

**Note**: Backend extracts UserId from JWT and resolves tenant automatically. The `sql` you send is the query the assistant already ran (from a `results` payload's `sql` field).

> **Security (new):** the endpoint now **validates** the submitted SQL — only `SELECT`s and whitelisted stored-procedure calls are allowed; anything else (DROP/DELETE/etc.) is rejected with **400**. RBAC filters are still injected server-side. Only pass a `sql` string that came back from a `results` event; do not hand-build DML.

**Request Body**:
```json
{
  "sql": "SELECT * FROM AssetJourney WHERE CustomerId = 376 AND StartTime >= '2026-06-01'"
}
```

**Request Example**:
```javascript
const sql = "SELECT * FROM AssetJourney WHERE StartTime >= '2026-06-01'";

const response = await fetch('http://localhost:8000/api/export/csv', {
    method: 'POST',
    headers: {
        'Authorization': `Bearer ${accessToken}`,
        'Content-Type': 'application/json'
    },
    body: JSON.stringify({ sql })
});

// Download as file
const blob = await response.blob();
const url = URL.createObjectURL(blob);
const a = document.createElement('a');
a.href = url;
a.download = `fleet_data_${Date.now()}.csv`;
a.click();
URL.revokeObjectURL(url);
```

**Success Response**: CSV file download

**CSV Format**:
```csv
AssetId,DriverId,StartTime,EndTime,JourneyDistanceTravelled,IdleDuration
1001,5001,2026-06-01 08:30:00,2026-06-01 12:45:00,125.5,15.2
1002,5002,2026-06-01 09:00:00,2026-06-01 14:30:00,98.3,8.7
```

**Error Responses**:
```json
// 400 Bad Request
{
  "detail": "SQL query is required"
}

// 403 Forbidden
{
  "detail": "SQL execution failed: Invalid object name 'UnauthorizedTable'"
}
```

**Important**: 
- The backend automatically applies RBAC filtering to the SQL query
- Users can only export data they have permission to access
- SQL injection protection is applied

---

## Complete Integration Example

### Full Implementation

```javascript
import { io } from "socket.io-client";

class NavigattoAIClient {
    constructor(baseUrl = "http://localhost:8000") {
        this.baseUrl = baseUrl;
        this.socket = null;
        this.currentThreadId = null;
        this.accessToken = null;
    }

    // ============================================
    // 1. SET JWT TOKEN (from your auth system)
    // ============================================
    
    setToken(jwtToken) {
        this.accessToken = jwtToken;
        localStorage.setItem('access_token', jwtToken);
    }

    // ============================================
    // 2. WEBSOCKET CONNECTION
    // ============================================
    
    connectWebSocket(callbacks = {}) {
        this.socket = io(this.baseUrl, {
            path: "/socket.io/",
            auth: {
                token: this.accessToken  // Only JWT required
            },
            transports: ["websocket"],
            reconnection: true,
            reconnectionAttempts: 10,
            reconnectionDelay: 1000
        });

        // Connection events
        this.socket.on("connect", () => {
            console.log("✅ Connected to AI Assistant");
            callbacks.onConnect?.();
        });

        this.socket.on("disconnect", (reason) => {
            console.log("❌ Disconnected:", reason);
            callbacks.onDisconnect?.(reason);
        });

        this.socket.on("connect_error", (error) => {
            console.error("Connection error:", error.message);
            callbacks.onError?.(error);
        });

        // Chat events
        this.socket.on("chat:start", (data) => {
            this.currentThreadId = data.thread_id;
            callbacks.onChatStart?.(data);
        });

        this.socket.on("chat:token", (data) => {
            callbacks.onToken?.(data.content);
        });

        this.socket.on("chat:data", (data) => {
            callbacks.onData?.(data);
        });

        this.socket.on("chat:error", (data) => {
            callbacks.onChatError?.(data.message);
        });

        this.socket.on("chat:done", () => {
            callbacks.onChatDone?.();
        });

        return this.socket;
    }

    // ============================================
    // 3. SEND MESSAGE
    // ============================================
    
    sendMessage(message, threadId = null) {
        if (!this.socket || !this.socket.connected) {
            throw new Error("WebSocket not connected");
        }

        this.socket.emit("chat_message", {
            message,
            thread_id: threadId || this.currentThreadId
        });
    }

    startNewConversation() {
        this.currentThreadId = null;
    }

    // ============================================
    // 4. THREAD MANAGEMENT
    // ============================================
    
    async getThreads(limit = 50, offset = 0) {
        const response = await fetch(
            `${this.baseUrl}/api/threads/?limit=${limit}&offset=${offset}`,
            {
                headers: {
                    'Authorization': `Bearer ${this.accessToken}`
                }
            }
        );

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to fetch threads');
        }

        return await response.json();
    }

    async getThreadMessages(threadId, limit = 100, offset = 0) {
        const response = await fetch(
            `${this.baseUrl}/api/threads/${threadId}/messages?limit=${limit}&offset=${offset}`,
            {
                headers: {
                    'Authorization': `Bearer ${this.accessToken}`
                }
            }
        );

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to fetch messages');
        }

        return await response.json();
    }

    async deleteThread(threadId) {
        const response = await fetch(
            `${this.baseUrl}/api/threads/${threadId}`,
            {
                method: 'DELETE',
                headers: {
                    'Authorization': `Bearer ${this.accessToken}`
                }
            }
        );

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to delete thread');
        }

        // If deleted thread was active, start new conversation
        if (threadId === this.currentThreadId) {
            this.startNewConversation();
        }

        return await response.json();
    }

    // ============================================
    // 5. CSV EXPORT
    // ============================================
    
    async exportToCSV(sql, filename = null) {
        const response = await fetch(`${this.baseUrl}/api/export/csv`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${this.accessToken}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ sql })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Export failed');
        }

        // Download file
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename || `export_${Date.now()}.csv`;
        a.click();
        URL.revokeObjectURL(url);
    }

    // ============================================
    // 6. CLEANUP
    // ============================================
    
    disconnect() {
        if (this.socket) {
            this.socket.disconnect();
            this.socket = null;
        }
    }
}

// ============================================
// PRODUCTION USAGE EXAMPLE
// ============================================

async function productionExample() {
    const client = new NavigattoAIClient("https://your-api-domain.com");

    try {
        // 1. Get JWT from YOUR auth system
        const jwtToken = await yourAuthSystem.login("user@example.com", "password");
        
        // 2. Set the JWT token
        client.setToken(jwtToken);
        console.log("JWT token set");

        // 3. Connect WebSocket (backend resolves tenant from JWT)
        client.connectWebSocket({
            onConnect: () => {
                console.log("WebSocket connected!");
            },
            
            onChatStart: (data) => {
                console.log("Chat started, thread:", data.thread_id);
            },
            
            onToken: (content) => {
                // Append to UI in real-time
                document.getElementById('ai-response').textContent += content;
            },
            
            onData: (data) => {
                if (data.event === "results") {
                    console.log("Results:", data.rows);
                    // Render table or chart
                }
            },
            
            onChatDone: () => {
                console.log("Response complete!");
                // Re-enable input, stop loading
            },
            
            onChatError: (message) => {
                console.error("Chat error:", message);
                alert(message);
            }
        });

        // 3. Send message
        setTimeout(() => {
            client.sendMessage("Show me top performing drivers this month");
        }, 1000);

        // 4. Load thread history
        setTimeout(async () => {
            const threads = await client.getThreads();
            console.log("Thread history:", threads);
            
            // Display in sidebar
            displayThreads(threads);
        }, 3000);

        // 5. Export data
        setTimeout(async () => {
            await client.exportToCSV(
                "SELECT * FROM AssetJourney WHERE StartTime >= '2026-06-01'",
                "june_journeys.csv"
            );
        }, 5000);

    } catch (error) {
        console.error("Error:", error.message);
    }
}

// Helper function to display threads
function displayThreads(threads) {
    const container = document.getElementById('thread-list');
    container.innerHTML = threads.map(thread => `
        <div class="thread-item" onclick="loadThread('${thread.id}')">
            <div class="thread-title">${thread.title}</div>
            <div class="thread-meta">
                ${thread.message_count} messages • ${formatDate(thread.updated_at)}
            </div>
            <button onclick="deleteThread(event, '${thread.id}')">🗑️</button>
        </div>
    `).join('');
}

async function loadThread(threadId) {
    const messages = await client.getThreadMessages(threadId);
    // Display messages in chat UI
    displayMessages(messages);
    client.currentThreadId = threadId;
}

async function deleteThread(event, threadId) {
    event.stopPropagation();
    if (confirm('Delete this conversation?')) {
        await client.deleteThread(threadId);
        // Reload thread list
        const threads = await client.getThreads();
        displayThreads(threads);
    }
}
```

---

## Error Handling

### Common Errors and Solutions

| Error | Cause | Solution |
|-------|-------|----------|
| `"Authorization header missing"` | No JWT token in request | Include `Authorization: Bearer {token}` header |
| `"Invalid token"` | JWT expired or invalid | Re-login to get new token |
| `"User not found in AspNetUsers"` | UserId from JWT not found | Verify user exists in AspNetUsers table |
| `"User not found in tenant database"` | User doesn't exist in tenant | Verify user has access to this tenant |
| `"Thread not found or not owned by user"` | Invalid thread ID or access denied | Check thread ID and user permissions |
| `"Not authenticated"` | WebSocket auth failed | Reconnect with valid JWT and domain |
| `"RBAC loading failed"` | User has no RBAC context | Contact admin to configure user permissions |

### Error Handling Best Practices

```javascript
// 1. Handle JWT token refresh
async function ensureValidToken() {
    const token = localStorage.getItem('access_token');
    
    // Check if token is expired (decode and check exp)
    const payload = JSON.parse(atob(token.split('.')[1]));
    const isExpired = payload.exp * 1000 < Date.now();
    
    if (isExpired) {
        // Get new token from YOUR auth system
        const newToken = await yourAuthSystem.refreshToken();
        client.setToken(newToken);
    }
}

// 2. Handle WebSocket disconnections
client.connectWebSocket({
    onDisconnect: (reason) => {
        if (reason === "io server disconnect") {
            // Server disconnected, manual reconnection needed
            client.connectWebSocket();
        }
        // "io client disconnect" = manual disconnect, don't reconnect
        // "ping timeout" = network issue, auto-reconnect will handle
    },
    
    onError: (error) => {
        if (error.message.includes("Invalid token")) {
            // Token expired, re-login required
            redirectToLogin();
        }
    }
});

// 3. Handle API errors
async function safeAPICall(apiFunction, fallback = null) {
    try {
        return await apiFunction();
    } catch (error) {
        console.error("API Error:", error.message);
        
        if (error.message.includes("401") || error.message.includes("Invalid token")) {
            redirectToLogin();
        }
        
        return fallback;
    }
}

// Usage
const threads = await safeAPICall(
    () => client.getThreads(),
    [] // Return empty array on error
);
```

---

## Best Practices

### 1. Security

✅ **DO**:
- Always use HTTPS/WSS in production
- Store JWT in `localStorage` or secure cookie
- Include `Authorization: Bearer {JWT}` header on all API calls
- Validate JWT expiration on frontend
- Implement token refresh mechanism
- Clear credentials on logout
- Let backend handle tenant resolution (don't send domain)

❌ **DON'T**:
- Store JWT in URL parameters
- Send credentials in WebSocket messages
- Hardcode domain or credentials
- Share JWT between users
- Use HTTP/WS in production

### 2. Performance

✅ **DO**:
- Enable WebSocket reconnection
- Implement exponential backoff for retries
- Batch thread list requests
- Cache thread data locally
- Debounce user input before sending messages
- Use pagination for large datasets

❌ **DON'T**:
- Create new WebSocket connections for each message
- Load all threads at once without pagination
- Send messages on every keystroke
- Keep disconnected sockets open

### 3. User Experience

✅ **DO**:
- Show real-time token streaming
- Display loading states during processing
- Provide visual feedback for errors
- Auto-save thread ID after `chat:start`
- Reload thread list after new conversations
- Confirm before deleting threads
- Show thread titles in sidebar

❌ **DON'T**:
- Wait for `chat:done` before showing response
- Hide errors from users
- Allow sending empty messages
- Delete threads without confirmation

### 4. Thread Management

✅ **DO**:
- Set `thread_id: null` for new conversations
- Save thread ID from `chat:start` event
- Pass saved thread ID for follow-up messages
- Reload thread list after creating/deleting threads
- Display thread titles (auto-generated from first message)
- Show message count and last updated time

❌ **DON'T**:
- Reuse thread IDs across different conversations
- Forget to update `currentThreadId` after `chat:start`
- Mix messages from different threads

### 5. Error Recovery

✅ **DO**:
- Implement retry logic with exponential backoff
- Show user-friendly error messages
- Log errors for debugging
- Provide fallback UI for failed requests
- Handle network timeouts gracefully
- Redirect to login on authentication errors

❌ **DON'T**:
- Silently swallow errors
- Show technical error messages to users
- Retry indefinitely without limit
- Ignore connection state changes

---

## API Reference Summary

### Authentication
**No authentication endpoints.** Use JWT from your own auth system.

### Thread Management
| Method | Endpoint | Headers | Description |
|--------|----------|---------|-------------|
| GET | `/api/threads/` | `Authorization` | Get all user threads |
| GET | `/api/threads/{id}/messages` | `Authorization` | Get thread messages |
| DELETE | `/api/threads/{id}` | `Authorization` | Delete thread |

### Data Export
| Method | Endpoint | Headers | Description |
|--------|----------|---------|-------------|
| POST | `/api/export/csv` | `Authorization`, `Content-Type` | Export data as CSV |

### WebSocket Events

**Client → Server**:
| Event | Payload | Description |
|-------|---------|-------------|
| `chat_message` | `{message, thread_id}` | Send user query (max 2000 chars) |
| `chat_stop` | `{request_id?, thread_id?}` | Cancel the in-flight request (Stop button) |

**Server → Client**:
| Event | Payload | Description |
|-------|---------|-------------|
| `chat:start` | `{thread_id, request_id}` | Processing started (`request_id` for Stop) |
| `chat:token` | `{content}` | Streaming response token |
| `chat:data` | `{event, ...}` | Structured data: `event` ∈ `results` / `sql` / `suggestions` / `agent_status` |
| `chat:stopping` | `{request_id}` | Stop acknowledged |
| `chat:stopped` | `{request_id, thread_id}` | Request cancelled — reset UI |
| `chat:error` | `{message}` | Error occurred |
| `chat:done` | `{}` | Processing complete |

**Notes:**
- `chat:data` with `event: "agent_status"` (`{stage, sp?}`) streams pipeline progress — **optional**, gated by backend `EMIT_AGENT_STATUS`.
- `GET /api/threads/{id}/messages` returns a `metadata` JSON string on assistant messages for **chart/data replay** (see Thread Management).

---

## Support

For issues or questions:
- **Backend API**: Check server logs for detailed error messages
- **WebSocket**: Monitor browser console for connection events
- **Authentication**: Verify JWT token validity and domain configuration
- **RBAC**: Contact admin to verify user permissions
