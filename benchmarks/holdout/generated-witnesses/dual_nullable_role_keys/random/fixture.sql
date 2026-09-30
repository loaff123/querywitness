-- QueryWitness fixture. Inspect supplied queries before running.
PRAGMA foreign_keys=ON;
BEGIN TRANSACTION;
CREATE TABLE "account" ("account_id" INTEGER NOT NULL,"handle" TEXT NOT NULL,PRIMARY KEY ("account_id"),UNIQUE ("handle"));
CREATE TABLE "review_job" ("job_id" INTEGER NOT NULL,"creator_id" INTEGER,"approver_id" INTEGER,PRIMARY KEY ("job_id"),FOREIGN KEY ("creator_id") REFERENCES "account"("account_id") DEFERRABLE INITIALLY DEFERRED,FOREIGN KEY ("approver_id") REFERENCES "account"("account_id") DEFERRABLE INITIALLY DEFERRED);
INSERT INTO "account" VALUES(202,'élise');
INSERT INTO "account" VALUES(303,'東京');
INSERT INTO "review_job" VALUES(12,303,202);
COMMIT;

-- Reference query
SELECT j.job_id,c.handle,a.handle FROM review_job AS j LEFT JOIN account AS c ON c.account_id=j.creator_id LEFT JOIN account AS a ON a.account_id=j.approver_id;

-- Candidate query
SELECT j.job_id,c.handle,a.handle FROM review_job AS j LEFT JOIN account AS c ON c.account_id=j.creator_id LEFT JOIN account AS a ON a.account_id=j.creator_id;
