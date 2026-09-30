-- QueryWitness fixture. Inspect supplied queries before running.
PRAGMA foreign_keys=ON;
BEGIN TRANSACTION;
CREATE TABLE "t" ("x" INTEGER);
INSERT INTO "t" VALUES(20);
INSERT INTO "t" VALUES(20);
COMMIT;

-- Reference query
SELECT SUM(x) FROM t;

-- Candidate query
SELECT SUM(DISTINCT x) FROM t;
