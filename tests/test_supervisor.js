/**
 * Test suite for the BackendSupervisor process lifecycle, auto-restart, and circuit breaker.
 */

const assert = require("assert");
const http = require("http");
const { BackendSupervisor } = require("../scripts/supervisor");

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function checkHttpHealth(port = 8000) {
  return new Promise((resolve) => {
    http.get(`http://127.0.0.1:${port}/health`, (res) => {
      resolve(res.statusCode === 200);
    }).on("error", () => resolve(false));
  });
}

async function runTests() {
  console.log("==================================================");
  console.log("     Running BackendSupervisor Unit Tests         ");
  console.log("==================================================");

  // --- Test 1: Normal Startup & Health Verification ---
  console.log("\n>>> Test 1: Normal Startup & Health Verification...");
  const supervisor = new BackendSupervisor({
    maxRestartsInWindow: 3,
    windowMs: 5000,
    initialBackoffMs: 200,
    maxBackoffMs: 1000,
  });

  await supervisor.start();
  let initialStatus = supervisor.getStatus();
  for (let i = 0; i < 30; i++) {
    await sleep(150);
    initialStatus = supervisor.getStatus();
    if (initialStatus.status === "HEALTHY") break;
  }

  console.log(`Supervisor status: ${initialStatus.status}, PID: ${initialStatus.pid}`);
  assert.strictEqual(initialStatus.status, "HEALTHY", "Supervisor should be HEALTHY after start");
  assert.ok(initialStatus.pid > 0, "PID should be a valid positive integer");

  const isHealthy = await checkHttpHealth(supervisor.port);
  assert.strictEqual(isHealthy, true, "Backend HTTP /health should return 200 OK");
  console.log("✅ Test 1 Passed: Backend initialized and healthy.");

  // --- Test 2: External Kill & Automatic Restart ---
  console.log("\n>>> Test 2: External Kill & Automatic Restart...");
  const firstPid = supervisor.pid;
  console.log(`Killing backend PID ${firstPid} externally with SIGKILL...`);
  process.kill(firstPid, "SIGKILL");

  console.log("Waiting for supervisor to detect crash and auto-restart...");
  let restartedStatus = supervisor.getStatus();
  for (let i = 0; i < 20; i++) {
    await sleep(200);
    restartedStatus = supervisor.getStatus();
    if (restartedStatus.status === "HEALTHY") break;
  }

  console.log(`Supervisor status: ${restartedStatus.status}, New PID: ${restartedStatus.pid}`);
  assert.strictEqual(restartedStatus.status, "HEALTHY", "Supervisor should recover back to HEALTHY");
  assert.ok(restartedStatus.pid > 0, "New PID should exist");
  assert.notStrictEqual(restartedStatus.pid, firstPid, "New PID must be different from killed PID");
  assert.ok(restartedStatus.restartsInWindow >= 1, "Should record at least 1 restart in sliding window");
  console.log("✅ Test 2 Passed: Backend successfully auto-restarted after crash.");

  // --- Test 3: Circuit Breaker Trips on Repeated Crashes ---
  console.log("\n>>> Test 3: Repeated Crashes Trip Circuit Breaker...");
  let circuitTrippedFired = false;
  supervisor.on("circuit_tripped", () => {
    circuitTrippedFired = true;
  });

  // Kill PID 2 more times to exceed maxRestartsInWindow (3)
  console.log(`Killing PID ${supervisor.pid} (Crash 2)...`);
  process.kill(supervisor.pid, "SIGKILL");
  
  // Wait for restart from crash 2
  for (let i = 0; i < 20; i++) {
    await sleep(100);
    if (supervisor.pid) break;
  }

  console.log(`Killing PID ${supervisor.pid} (Crash 3 - should trip circuit breaker)...`);
  process.kill(supervisor.pid, "SIGKILL");
  await sleep(800);

  const trippedStatus = supervisor.getStatus();
  console.log(`Supervisor status after 3 crashes: ${trippedStatus.status}`);
  assert.strictEqual(trippedStatus.status, "CIRCUIT_TRIPPED", "Supervisor should be in CIRCUIT_TRIPPED state");
  assert.strictEqual(trippedStatus.circuitTripped, true, "circuitTripped boolean must be true");
  assert.strictEqual(circuitTrippedFired, true, "circuit_tripped event must have been emitted");
  assert.ok(trippedStatus.errorMessage.includes("Circuit breaker tripped"), "Error message must describe circuit trip");
  console.log("✅ Test 3 Passed: Circuit breaker tripped cleanly after exceeding max restarts.");

  // Clean up
  supervisor.stop();
  console.log("\n==================================================");
  console.log("  ✅ All BackendSupervisor Tests Passed!         ");
  console.log("==================================================");
}

runTests().catch((err) => {
  console.error("❌ Test Failed:", err);
  process.exit(1);
});
