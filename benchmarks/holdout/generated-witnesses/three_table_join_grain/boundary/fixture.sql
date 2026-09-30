-- QueryWitness fixture. Inspect supplied queries before running.
PRAGMA foreign_keys=ON;
BEGIN TRANSACTION;
CREATE TABLE "annotation" ("purchase_id" INTEGER NOT NULL,"label" TEXT NOT NULL,UNIQUE ("purchase_id","label"),FOREIGN KEY ("purchase_id") REFERENCES "purchase"("purchase_id") DEFERRABLE INITIALLY DEFERRED);
CREATE TABLE "purchase" ("purchase_id" INTEGER NOT NULL,PRIMARY KEY ("purchase_id"));
CREATE TABLE "purchase_line" ("purchase_id" INTEGER NOT NULL,"units" INTEGER NOT NULL,FOREIGN KEY ("purchase_id") REFERENCES "purchase"("purchase_id") DEFERRABLE INITIALLY DEFERRED);
INSERT INTO "purchase" VALUES(17);
INSERT INTO "purchase_line" VALUES(17,5);
COMMIT;

-- Reference query
SELECT p.purchase_id,SUM(l.units) FROM purchase AS p JOIN purchase_line AS l ON l.purchase_id=p.purchase_id GROUP BY p.purchase_id;

-- Candidate query
SELECT p.purchase_id,SUM(l.units) FROM purchase AS p JOIN purchase_line AS l ON l.purchase_id=p.purchase_id JOIN annotation AS a ON a.purchase_id=p.purchase_id GROUP BY p.purchase_id;
