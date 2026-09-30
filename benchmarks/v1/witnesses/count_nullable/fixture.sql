-- QueryWitness fixture. Inspect supplied queries before running.
PRAGMA foreign_keys=ON;
BEGIN TRANSACTION;
CREATE TABLE "t" ("x" INTEGER);
INSERT INTO "t" VALUES(NULL);
COMMIT;

-- Reference query
SELECT COUNT(x) FROM t;

-- Candidate query
SELECT COUNT(*) FROM t;
