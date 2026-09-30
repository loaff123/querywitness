-- QueryWitness fixture. Inspect supplied queries before running.
PRAGMA foreign_keys=ON;
BEGIN TRANSACTION;
CREATE TABLE "c" ("pid" INTEGER,"amount" INTEGER,FOREIGN KEY ("pid") REFERENCES "p"("id") DEFERRABLE INITIALLY DEFERRED);
CREATE TABLE "p" ("id" INTEGER NOT NULL,PRIMARY KEY ("id"));
INSERT INTO "c" VALUES(1,10);
INSERT INTO "c" VALUES(1,20);
INSERT INTO "p" VALUES(1);
COMMIT;

-- Reference query
SELECT p.id FROM p WHERE EXISTS (SELECT 1 FROM c WHERE c.pid=p.id);

-- Candidate query
SELECT p.id FROM p JOIN c ON c.pid=p.id;
