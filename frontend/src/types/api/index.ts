/**
 * Authoritative frontend type root. Every DTO mirrors its backend schema
 * (app/schemas/*, app/security/*) — see per-file headers. UI-facing view
 * models live in src/adapters/* (explicit DTO → view transforms).
 */
export * from "./common";
export * from "./auth";
export * from "./health";
export * from "./admin";
export * from "./agents";
export * from "./analytics";
export * from "./audit";
export * from "./compliance";
export * from "./copilot";
export * from "./documents";
export * from "./governance";
export * from "./knowledgeGraph";
export * from "./research";
export * from "./risk";
