-- QueryWitness fixture. Inspect supplied queries before running.
PRAGMA foreign_keys=ON;
BEGIN TRANSACTION;
CREATE TABLE "t" ("x" INTEGER);
INSERT INTO "t" VALUES(NULL);
COMMIT;

-- Reference query
SELECT x FROM t WHERE x IS NULL OR x<>1;

-- Candidate query
SELECT x FROM t WHERE NOT (x=1);
