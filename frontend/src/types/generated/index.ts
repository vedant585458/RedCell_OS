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
