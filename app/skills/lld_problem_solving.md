---

# LLD Problem Solving

## Overview

Five phases in ~35 minutes. Principles and SOLID checks are woven into each phase — not bolted on at the end.

**Two hard rules before touching code:**
1. Name the design pattern before writing a single class.
2. Make illegal states unrepresentable — validate at construction, not at the call site.

---

## Phase 1 — Requirements (~5 min)

Three explicit steps — do not skip any.

### Step 1a — Receive and restate the problem

The interviewer gives a broad prompt (e.g., *"Design a music player supporting play, next/prev, and repeat modes"*). Before asking anything, restate it in your own words in one sentence to confirm you've understood the scope.

### Step 1b — Ask clarifying questions

Ask targeted questions across these categories. Pick the 3–4 most relevant; don't ask all of them or it reads as stalling.

| Category | Questions to consider |
|----------|-----------------------|
| **Functional scope** | What operations must be supported? What's explicitly excluded? |
| **Edge cases & boundaries** | What happens at the last/first item? What if the collection is empty? |
| **State transitions** | Which transitions are illegal? What does calling X on state Y do? |
| **Concurrency** | Do multiple users/threads access shared state? What consistency is required? |
| **Persistence** | In-memory only, or does state survive restarts? |
| **Error handling** | Reject invalid input, or silently ignore? |
| **Pricing / auth / payment** | Almost always out of scope — confirm explicitly |

**Rule:** If the interviewer says "use your judgement" — state your assumption aloud and move on. Don't stall.

### Step 1c — Produce finalized requirements

Output two lists before touching entities:

**IN scope:**
- [one sentence per requirement]

**OUT of scope:**
- [explicitly confirmed exclusions]

**Principle checks:**
- **YAGNI:** If the interviewer didn't ask for it, don't design for it.
- **KISS:** Can each requirement be stated in one sentence? If not, clarify further.

---

## Phase 2 — Data Models (~3 min)

Identify the **stored entities** first — nouns from requirements that map to a repository or in-memory store. These are pure data; no behaviour beyond construction validation.

For each ask:
- Is it **immutable and identified by value**? → `record`
- Does it wrap a primitive to prevent ID mix-ups? → typed wrapper `record`
- Does it hold **mutable state** that changes over time? → class with controlled mutation

```java
// ✅ typed wrapper — compiler prevents mixing up IDs
record TrackId(String value) {
    TrackId { if (value == null || value.isBlank()) throw new IllegalArgumentException(); }
}
// ✅ value object — immutable, validated at construction
record Track(TrackId id, String title, String artist, long durationMs) {}
```

Map relationships between data models with a box-and-arrow sketch (no UML needed):
- What does each model own directly?
- Where is ordering or position captured?

**Do not put services or state machines here.** `MusicPlayer` is not a data model — it's never persisted.

---

## Phase 3 — Class & Interface Design (~10–15 min)

Design the **behavioural layer** — services, orchestrators, state machines, enums, interfaces. These operate on the data models from Phase 2 but are never stored themselves.

Start by naming the pattern before writing any class.

For each service/orchestrator define **runtime state** (fields) and **behaviour** (methods). Rule: keep rules with the class that owns the relevant state.

### Step 3a — Make Illegal States Unrepresentable

```java
// ❌ status field allows impossible combinations
class Order { OrderStatus status; LocalDateTime shippedAt; } // PENDING order with shippedAt?

// ✅ sealed interface — shape of data reflects valid states only
sealed interface Order permits Pending, Shipped, Cancelled {}
record Pending(OrderId id, Instant createdAt) implements Order {}
record Shipped(OrderId id, Instant shippedAt) implements Order {}
```

Never store what can be derived:
```java
// ❌ mutable balance field — can drift from truth
class Account { BigDecimal balance; }

// ✅ balance derived from immutable ledger entries — always auditable
BigDecimal balance() { return entries.stream()
    .map(e -> e.type() == CREDIT ? e.amount() : e.amount().negate())
    .reduce(BigDecimal.ZERO, BigDecimal::add); }
```

### Step 3b — Name the Pattern Before Writing Code

| Situation | Pattern | Signal |
|-----------|---------|--------|
| Behaviour changes based on internal state | **State** | `interface PlayerState`; each state handles its own transitions |
| Algorithm swapped by the caller externally | **Strategy** | Interface injected via constructor |
| New type = new class, zero existing changes | **OCP via Interface + Registry** | `Map<Type, Handler>` — the Aspora `TransactionProcessor` model |
| Notify multiple subscribers of an event | **Observer** | `List<Listener>`, `notifyAll()` |
| Fixed algorithm skeleton, steps vary | **Template Method** | `abstract class Pipeline`, concrete subclasses fill steps |
| Create objects without specifying class | **Factory Method** | `OrderFactory.create(type)` |
| Abstract data access | **Repository** | `interface TrackRepository`, `InMemoryTrackRepository` |

**State vs Strategy — the confirmed interview trap:**
- **State:** the object decides behaviour based on its own internal state. `play()` behaves differently when STOPPED vs PAUSED — the *state object* handles the transition.
- **Strategy:** the *caller* decides which algorithm to inject at construction time.
- Both use an interface. The distinction is **who controls the switch**. Name it correctly before the interviewer has to ask.

**OCP via registry (from Aspora TMS):**
```java
// New transaction type = one new class + one registration line. Zero existing changes.
interface TransactionProcessor { void process(Transaction tx); }
class TransferProcessor implements TransactionProcessor { ... }
class DepositProcessor implements TransactionProcessor { ... }

class ProcessorRegistry {
    private final Map<TransactionType, TransactionProcessor> registry;
    TransactionProcessor get(TransactionType type) { return registry.get(type); }
}
```
Apply the same model to: enrichers, validators, notification channels, repeat modes, state transitions.

### Step 3c — SOLID Checklist

| Principle | Question | Fix if violated |
|-----------|----------|-----------------|
| **SRP** | One reason to change? | Split the class |
| **OCP** | New behaviour without modifying existing class? | Interface + registry |
| **LSP** | Subtypes substitutable everywhere parent is used? | Fix subtype contract |
| **ISP** | Interfaces small and focused? | Split fat interfaces |
| **DIP** | High-level classes depend on abstractions? | Introduce interface/port |

**DRY:** Repeated logic in two places? Extract to a shared method.  
**SoC:** Is one class doing orchestration + validation + persistence? Separate them.  
**KISS:** Would a simpler design satisfy requirements? Use it.

---

## Phase 4 — Implementation (~10 min)

Ask the interviewer first: *"Do you want working code or pseudocode?"*

Implement in this order:
1. **Happy path** — show class cooperation end-to-end
2. **Edge cases** — invalid inputs, illegal transitions, empty collections
3. **Verification** — trace a concrete scenario (e.g., "play() called on a paused player with REPEAT_ONE active")

**State transition guard:**
```java
public class StoppedState implements PlayerState {
    @Override public void pause(MusicPlayer player) {
        throw new IllegalStateException("Cannot pause a stopped player");
    }
    @Override public void play(MusicPlayer player) {
        player.setState(new PlayingState()); // valid transition
    }
}
```

**Separate mode from state:**
```java
public class MusicPlayer {
    private PlayerState state = new StoppedState(); // what the player IS doing
    private RepeatMode repeatMode = RepeatMode.NONE; // what happens when a track ends
    private Playlist playlist;
    private int currentIndex;
}
```

**Concurrency — when the problem involves shared resources:**
- Shared resource accessed by multiple threads → `ReentrantLock` or `synchronized`
- Priority queue + multiple consumers → `PriorityBlockingQueue` (thread-safe)
- Low-priority starvation risk → aging: increase priority after waiting N seconds
- Multiple locks needed → **always acquire in a consistent order** (prevents deadlock)

---

## Phase 5 — Extensibility (~5 min, if time allows)

When the interviewer asks "how would you add X?":
- Point to the **single class** that changes
- Confirm nothing else needs to change — that's the payoff of clean boundaries
- Name which principle made this extension cheap

Example: "Adding SHUFFLE only touches the `next()` delegation logic in `MusicPlayer` and the `RepeatMode` enum. No state classes change — that's OCP."

---

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Jumping to code before entities are mapped | Always produce a box diagram first |
| Calling State pattern "Strategy" | Know the distinction cold: who controls the switch? |
| Storing balance / derived values as mutable fields | Derive from immutable history |
| Putting RepeatMode inside state objects | SoC — state and mode are separate concerns |
| Fat orchestrator doing orchestration + validation + persistence | Distribute responsibilities |
| if-else chains on a type/status field | Interface + registry (OCP) or State pattern |
| Primitive obsession: `String userId`, `int accountId` | Typed wrappers as records |
| Validating inputs downstream, not at construction | Validate in the constructor; once built, always valid |
| Designing for scale not in the requirements | YAGNI |

---

## Quick Reference

```java
// Value objects and typed IDs → records (immutable, self-validating)
record TrackId(String value) {
    TrackId { if (value == null || value.isBlank()) throw new IllegalArgumentException(); }
}
record Track(TrackId id, String title, Duration duration) {}

// State machine → sealed interface (compiler enforces exhaustiveness)
sealed interface PlayerState permits PlayingState, PausedState, StoppedState {
    void play(MusicPlayer player);
    void pause(MusicPlayer player);
    void stop(MusicPlayer player);
    void next(MusicPlayer player);
}

// OCP via interface + registry
interface EnricherStrategy { EnrichedEvent enrich(RawEvent event); }
Map<EventType, List<EnricherStrategy>> enrichers = new HashMap<>();

// Concurrency — shared resource
private final ReentrantLock runwayLock = new ReentrantLock();
private final PriorityBlockingQueue<FlightRequest> requestQueue = new PriorityBlockingQueue<>();

// Money
BigDecimal price = new BigDecimal("10.1"); // never new BigDecimal(10.1)
a.compareTo(b) == 0                        // never a.equals(b) for BigDecimal
```
