/**
 * Authoritative frontend type root. Every DTO mirrors its backend schema
 * (app/schemas/*, app/security/*) — see per-file headers under api/.
 * UI-facing view models live in src/adapters/* (explicit DTO → view
 * transforms). Do NOT add hand-guessed fields here: verify against backend.
 */
export * from "./api/index";
