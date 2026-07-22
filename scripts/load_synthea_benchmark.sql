TRUNCATE TABLE synthea_native_benchmark.patients CASCADE;
TRUNCATE TABLE synthea_native_benchmark.encounters CASCADE;
TRUNCATE TABLE synthea_native_benchmark.conditions CASCADE;
TRUNCATE TABLE synthea_native_benchmark.medications CASCADE;
TRUNCATE TABLE synthea_native_benchmark.procedures CASCADE;
TRUNCATE TABLE synthea_native_benchmark.observations CASCADE;

TRUNCATE TABLE synthea_native_benchmark.organizations CASCADE;
TRUNCATE TABLE synthea_native_benchmark.providers CASCADE;

\copy synthea_native_benchmark.patients FROM '/tmp/synthea_csv/patients.csv' WITH (FORMAT csv, HEADER true);
\copy synthea_native_benchmark.encounters FROM '/tmp/synthea_csv/encounters.csv' WITH (FORMAT csv, HEADER true);
\copy synthea_native_benchmark.conditions FROM '/tmp/synthea_csv/conditions.csv' WITH (FORMAT csv, HEADER true);
\copy synthea_native_benchmark.medications FROM '/tmp/synthea_csv/medications.csv' WITH (FORMAT csv, HEADER true);
\copy synthea_native_benchmark.procedures FROM '/tmp/synthea_csv/procedures.csv' WITH (FORMAT csv, HEADER true);
\copy synthea_native_benchmark.observations FROM '/tmp/synthea_csv/observations.csv' WITH (FORMAT csv, HEADER true);
\copy synthea_native_benchmark.organizations FROM '/tmp/synthea_csv/organizations.csv' WITH (FORMAT csv, HEADER true);
\copy synthea_native_benchmark.providers FROM '/tmp/synthea_csv/providers.csv' WITH (FORMAT csv, HEADER true);
