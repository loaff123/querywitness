-- QueryWitness fixture. Inspect supplied queries before running.
PRAGMA foreign_keys=ON;
BEGIN TRANSACTION;
CREATE TABLE "reading" ("reading_id" INTEGER NOT NULL,"value" REAL,PRIMARY KEY ("reading_id"));
INSERT INTO "reading" VALUES(41,0.0);
INSERT INTO "reading" VALUES(42,0.5);
INSERT INTO "reading" VALUES(43,0.50000000000000011);
INSERT INTO "reading" VALUES(44,1.0);
INSERT INTO "reading" VALUES(45,NULL);
COMMIT;

-- Reference query
SELECT reading_id FROM reading WHERE value>=0.5 AND value<=1.0;

-- Candidate query
SELECT reading_id FROM reading WHERE value>0.5 AND value<1.0;
