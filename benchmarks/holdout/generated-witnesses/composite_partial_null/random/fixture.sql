-- QueryWitness fixture. Inspect supplied queries before running.
PRAGMA foreign_keys=ON;
BEGIN TRANSACTION;
CREATE TABLE "dispatch" ("ticket" INTEGER NOT NULL,"zone" TEXT,"slot" INTEGER,PRIMARY KEY ("ticket"),FOREIGN KEY ("zone","slot") REFERENCES "rack"("zone","slot") DEFERRABLE INITIALLY DEFERRED);
CREATE TABLE "rack" ("zone" TEXT NOT NULL,"slot" INTEGER NOT NULL,PRIMARY KEY ("zone","slot"));
INSERT INTO "dispatch" VALUES(36,NULL,9);
COMMIT;

-- Reference query
SELECT ticket FROM dispatch WHERE zone IS NULL OR slot IS NULL;

-- Candidate query
SELECT ticket FROM dispatch WHERE zone IS NULL AND slot IS NULL;
