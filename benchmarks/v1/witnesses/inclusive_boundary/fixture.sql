-- QueryWitness fixture. Inspect supplied queries before running.
PRAGMA foreign_keys=ON;
BEGIN TRANSACTION;
CREATE TABLE "t" ("x" INTEGER NOT NULL);
INSERT INTO "t" VALUES(10);
COMMIT;

-- Reference query
SELECT x FROM t WHERE x>=10;

-- Candidate query
SELECT x FROM t WHERE x>10;
