#!/usr/bin/env bash
set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPENAPI_JSON="${ROOT_DIR}/data/openapi.json"
OUTPUT_TS="${ROOT_DIR}/frontend/src/types/generated/backend.ts"
INDEX_TS="${ROOT_DIR}/frontend/src/types/generated/index.ts"

echo "=== Generating TypeScript Types from Backend Pydantic / OpenAPI Schema ==="

# 1. Export OpenAPI JSON from FastAPI backend
echo "1. Exporting OpenAPI schema from FastAPI..."
export PYTHONPATH="${HOME}/.local/lib/python3.11/site-packages:${ROOT_DIR}/backend/src:${PYTHONPATH:-}"
python3 "${ROOT_DIR}/scripts/export_openapi.py" "${OPENAPI_JSON}"

# 2. Run openapi-typescript to generate typed TS definitions
echo "2. Compiling TypeScript definitions..."
cd "${ROOT_DIR}/frontend"
npx openapi-typescript "${OPENAPI_JSON}" -o "${OUTPUT_TS}"

# 3. Generate index wrapper with convenient type aliases
cat << 'EOF' > "${INDEX_TS}"
/**
 * Auto-generated TypeScript definitions matching backend Pydantic models.
 * Generated via scripts/generate-types.sh from FastAPI OpenAPI schema.
 * DO NOT EDIT MANUALLY.
 */

import type { components, paths } from "./backend";

// Export raw generated OpenAPI schema namespaces
export type { components, paths };

// Convenient Schema Type Aliases
export type HealthResponse = components["schemas"]["HealthResponse"];
export type ProcessRecord = components["schemas"]["ProcessRecord"];
export type KillSwitchRequest = components["schemas"]["KillSwitchRequest"];
export type KillSwitchResponse = components["schemas"]["KillSwitchResponse"];
export type EventReplayResponse = components["schemas"]["EventReplayResponse"];
export type StoredEvent = components["schemas"]["StoredEvent"];
export type OrganizationHierarchyResponse = components["schemas"]["OrganizationHierarchyResponse"];
export type DepartmentWithEmployeesResponse = components["schemas"]["DepartmentWithEmployeesResponse"];
export type DepartmentResponse = components["schemas"]["DepartmentResponse"];
export type RoleResponse = components["schemas"]["RoleResponse"];
export type AgentResponse = components["schemas"]["AgentResponse"];
export type EngagementResponse = components["schemas"]["EngagementResponse"];
export type EngagementIntakeRequest = components["schemas"]["EngagementIntakeRequest"];
export type TargetScopeSchema = components["schemas"]["TargetScopeSchema"];
export type RulesOfEngagementSchema = components["schemas"]["RulesOfEngagementSchema"];
export type TimeWindowSchema = components["schemas"]["TimeWindowSchema"];
export type TaskResponse = components["schemas"]["TaskResponse"];
export type TaskManualOverrideRequest = components["schemas"]["TaskManualOverrideRequest"];
export type ValidationError = components["schemas"]["ValidationError"];
export type HTTPValidationError = components["schemas"]["HTTPValidationError"];
EOF

echo "3. TypeScript types successfully generated at frontend/src/types/generated/!"

# 4. If --check is passed, verify there is no drift against committed files
if [ "$1" == "--check" ]; then
  echo "Checking for schema drift in git..."
  cd "${ROOT_DIR}"
  if ! git diff --exit-code frontend/src/types/generated/; then
    echo "❌ ERROR: Generated TypeScript types are out of sync with backend Pydantic models!"
    echo "Run './scripts/generate-types.sh' locally and commit the updated types."
    exit 1
  fi
  echo "✅ TypeScript types match backend Pydantic models with zero drift."
fi

echo "=== Type Generation Complete ==="
