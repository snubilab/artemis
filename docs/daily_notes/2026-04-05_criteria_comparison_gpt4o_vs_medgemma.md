# TTE Criteria Comparison Across LLM Models

Generated: 2026-04-05 15:47

## 1. Cross-Study Summary

| Trial | Model | Study ID | Incl | Excl | HR (95% CI) | Tx N | Comp N |
|-------|-------|----------|------|------|-------------|------|--------|
| PLATO | gpt-4o | 480 | 16 | 28 | 0.750 (0.552-1.019) | 191 | 918 |
| PLATO | medgemma-27b | 522 | 5 | 23 | 1.000 (1.000-1.000) | 191 | 918 |
| PLATO | medgemma-4b | 525 | 0 | 0 | N/A | 0 | 0 |
| LEADER | gpt-4o | 481 | 35 | 60 | 0.748 (0.607-0.921) | 1150 | 581 |
| LEADER | medgemma-27b | 523 | 0 | 0 | N/A | 0 | 0 |
| LEADER | medgemma-4b | 526 | 31 | 32 | 0.666 (0.536-0.827) | 1150 | 581 |
| ARISTOTLE | gpt-4o | 482 | 13 | 19 | 1.418 (0.772-2.606) | 875 | 2305 |
| ARISTOTLE | medgemma-27b | 524 | 13 | 29 | 1.706 (0.898-3.239) | 875 | 2305 |
| ARISTOTLE | medgemma-4b | 527 | 17 | 21 | 1.706 (0.898-3.239) | 875 | 2305 |

## 2. PLATO

### PLATO — Study Metadata

| Model | Study ID | Incl | Excl | HR (95% CI) | Tx N | Comp N |
|-------|----------|------|------|-------------|------|--------|
| gpt-4o | 480 | 16 | 28 | 0.750 (0.552-1.019) | 191 | 918 |
| medgemma-27b | 522 | 5 | 23 | 1.000 (1.000-1.000) | 191 | 918 |
| medgemma-4b | 525 | 0 | 0 | N/A | 0 | 0 |

### PLATO — Inclusion Criteria

| # | gpt-4o Description | gpt-4o Concepts | medgemma-27b Description | medgemma-27b Concepts | medgemma-4b Description | medgemma-4b Concepts |
|---|---|---|---|---|---|---|
| 1 | Age 18 years or older | - | Age >= 18 | - | - | - |
| 2 | Hospitalized for chest pain and potential ACS | - | Acs (OR group) | - | - | - |
| 3 | ST-Elevation Myocardial Infarction (STEMI) | 4296653 | Hospitalized for chest pain and potential ACS | 319844, 608952, 1340441, 4108670 ...+4 | - | - |
| 4 | Non-ST-Elevation Myocardial Infarction (NSTEMI) | 4145721, 4270024, 35610091, 45766241, 46270162 | STEMI with intention for primary PCI | 3655133, 4296653 | - | - |
| 5 | Unstable Angina | 608952, 608953, 1340441, 4108670 ...+4 | STEMI with intention for primary PCI - procedure | 4216130 | - | - |
| 6 | Females of childbearing potential must have negative preg... | 4014769, 4017479, 4041161, 4042751 ...+7 | - | - | - | - |
| 7 | Females of childbearing potential must use reliable contr... | - | - | - | - | - |
| 8 | Use of oral contraceptive pills | 1515774 | - | - | - | - |
| 9 | Use of intrauterine device | 4225628 | - | - | - | - |
| 10 | Use of contraceptive implant | 2718684, 4118782, 4225628, 4232656, 45768316 | - | - | - | - |
| 11 | Use of contraceptive injection | 1500211, 1552310 | - | - | - | - |
| 12 | Use of barrier method | 4021168, 4024744, 4149369, 4152025 ...+3 | - | - | - | - |
| 13 | Use of sterilization procedure | 45766058, 45769367 | - | - | - | - |
| 14 | ST-segment elevation or new left bundle-branch block with... | - | - | - | - | - |
| 15 | ST-segment elevation | 4089480, 4146761, 37021258 | - | - | - | - |
| 16 | New left bundle-branch block | 316998 | - | - | - | - |

### PLATO — Exclusion Criteria

| # | gpt-4o Description | gpt-4o Concepts | medgemma-27b Description | medgemma-27b Concepts | medgemma-4b Description | medgemma-4b Concepts |
|---|---|---|---|---|---|---|
| 1 | Fibrinolytic therapy within 24 hours | - | Fibrinolytic therapy within 24 hours prior | 779889, 912476, 924151, 1315865 ...+34 | - | - |
| 2 | Alteplase administration | 19136184, 44790938 | Treatment with blood clotting agents that cannot be stopped | - | - | - |
| 3 | Reteplase administration | 1307515 | Treatment with Anticoagulants that cannot be stopped | 1322199, 1327256, 1344992, 1366428 ...+15 | - | - |
| 4 | Tenecteplase administration | 1352213 | Treatment with Antiplatelet agents that cannot be stopped | 4216130 | - | - |
| 5 | Streptokinase administration | 42801108, 44507865 | Prior invasive procedure for current ACS episode | 4064161 | - | - |
| 6 | Urokinase administration | 4132857 | Moderate or severe liver disease | - | - | - |
| 7 | Treatment with blood clotting agents that cannot be stopped | - | Moderate or severe Cirrhosis | 194990 | - | - |
| 8 | Treatment with Factor VIII | 854372, 1254255 | Moderate or severe Hepatitis | 194990, 3656096, 4055224, 4059290 ...+9 | - | - |
| 9 | Treatment with Factor IX | 1352141 | Moderate or severe Liver failure | 37162002 | - | - |
| 10 | Treatment with Fibrinogen | 4019655, 40489873, 44807975 | Moderate or severe Steatosis | 4027307, 4197819 | - | - |
| 11 | Treatment with Prothrombin Complex Concentrate | 4064161 | Moderate or severe Fibrosis | 4002478, 4049211, 4143915, 4195018 | - | - |
| 12 | Treatment with Recombinant Factor VIIa | 4029488 | Moderate or severe Cholestasis | 4130518 | - | - |
| 13 | Invasive procedure for current ACS episode | 199867, 4012113, 4026125, 4238978 ...+2 | Moderate or severe Liver cancer | 439847 | - | - |
| 14 | Moderate or severe liver disease | - | Contraindication against the use of clopidogrel | - | - | - |
| 15 | Cirrhosis of the liver | 4026032, 4058676, 4059281, 4250743 ...+4 | History of intracranial hemorrhage | 4027663 | - | - |
| 16 | Hepatic encephalopathy | 4135822, 36716713, 37164403 | History of peptic ulcer disease or gastrointestinal bleeding | 192671 | - | - |
| 17 | Chronic hepatitis | 4340953, 37164403 | History of gastrointestinal bleeding | 432870 | - | - |
| 18 | Acute liver failure | 201612 | History of severe thrombocytopenia | 1077464, 4048971, 4103376, 4140472 ...+4 | - | - |
| 19 | Primary biliary cholangitis | 194692, 4059290 | History of hypersensitivity to clopidogrel or thienopyrid... | 4048971, 4084167, 4103376, 4140472 ...+4 | - | - |
| 20 | Primary sclerosing cholangitis | 1077464, 4084167, 4103376, 4140472 ...+4 | History of hypersensitivity to thienopyridines | 603206, 762933, 763009, 4045734 ...+13 | - | - |
| 21 | Alcoholic liver disease | 766256, 4086850 | History of ischemic stroke | 373503, 374384, 4238191 | - | - |
| 22 | Non-alcoholic steatohepatitis | 439847, 4111721, 43530606 | History of transient ischemic attack | 313504, 1076101, 4205583, 4231757 ...+3 | - | - |
| 23 | Contraindication to clopidogrel | - | History of active bleeding diathesis | - | - | - |
| 24 | Allergy to clopidogrel | 194990, 4055224, 4159144, 4245975 ...+3 | - | - | - | - |
| 25 | Active bleeding | 432870 | - | - | - | - |
| 26 | History of intracranial hemorrhage | - | - | - | - | - |
| 27 | Severe hepatic impairment | - | - | - | - | - |
| 28 | Thrombocytopenia | - | - | - | - | - |

### PLATO — Concept ID Jaccard Similarity (ref: gpt-4o)

**gpt-4o vs medgemma-27b**

| Type | # | Ref Description | Jaccard | Shared | Ref-only | Other-only |
|------|---|-----------------|---------|--------|----------|------------|
| Incl | 1 | Age 18 years or older | 1.000 | 0 | 0 | 0 |
| Incl | 2 | Hospitalized for chest pain and poten... | 1.000 | 0 | 0 | 0 |
| Incl | 3 | ST-Elevation Myocardial Infarction (S... | 0.000 | 0 | 1 | 8 |
| Incl | 4 | Non-ST-Elevation Myocardial Infarctio... | 0.000 | 0 | 5 | 2 |
| Incl | 5 | Unstable Angina | 0.000 | 0 | 8 | 1 |
| Incl | 6 | Females of childbearing potential mus... | 0.000 | 0 | 11 | 0 |
| Incl | 7 | Females of childbearing potential mus... | 1.000 | 0 | 0 | 0 |
| Incl | 8 | Use of oral contraceptive pills | 0.000 | 0 | 1 | 0 |
| Incl | 9 | Use of intrauterine device | 0.000 | 0 | 1 | 0 |
| Incl | 10 | Use of contraceptive implant | 0.000 | 0 | 5 | 0 |
| Incl | 11 | Use of contraceptive injection | 0.000 | 0 | 2 | 0 |
| Incl | 12 | Use of barrier method | 0.000 | 0 | 7 | 0 |
| Incl | 13 | Use of sterilization procedure | 0.000 | 0 | 2 | 0 |
| Incl | 14 | ST-segment elevation or new left bund... | 1.000 | 0 | 0 | 0 |
| Incl | 15 | ST-segment elevation | 0.000 | 0 | 3 | 0 |
| Incl | 16 | New left bundle-branch block | 0.000 | 0 | 1 | 0 |
| Excl | 1 | Fibrinolytic therapy within 24 hours | 0.000 | 0 | 0 | 38 |
| Excl | 2 | Alteplase administration | 0.000 | 0 | 2 | 0 |
| Excl | 3 | Reteplase administration | 0.000 | 0 | 1 | 19 |
| Excl | 4 | Tenecteplase administration | 0.000 | 0 | 1 | 1 |
| Excl | 5 | Streptokinase administration | 0.000 | 0 | 2 | 1 |
| Excl | 6 | Urokinase administration | 0.000 | 0 | 1 | 0 |
| Excl | 7 | Treatment with blood clotting agents ... | 0.000 | 0 | 0 | 1 |
| Excl | 8 | Treatment with Factor VIII | 0.000 | 0 | 2 | 13 |
| Excl | 9 | Treatment with Factor IX | 0.000 | 0 | 1 | 1 |
| Excl | 10 | Treatment with Fibrinogen | 0.000 | 0 | 3 | 2 |
| Excl | 11 | Treatment with Prothrombin Complex Co... | 0.000 | 0 | 1 | 4 |
| Excl | 12 | Treatment with Recombinant Factor VIIa | 0.000 | 0 | 1 | 1 |
| Excl | 13 | Invasive procedure for current ACS ep... | 0.000 | 0 | 6 | 1 |
| Excl | 14 | Moderate or severe liver disease | 1.000 | 0 | 0 | 0 |
| Excl | 15 | Cirrhosis of the liver | 0.000 | 0 | 8 | 1 |
| Excl | 16 | Hepatic encephalopathy | 0.000 | 0 | 3 | 1 |
| Excl | 17 | Chronic hepatitis | 0.000 | 0 | 2 | 1 |
| Excl | 18 | Acute liver failure | 0.000 | 0 | 1 | 8 |
| Excl | 19 | Primary biliary cholangitis | 0.000 | 0 | 2 | 8 |
| Excl | 20 | Primary sclerosing cholangitis | 0.000 | 0 | 8 | 17 |
| Excl | 21 | Alcoholic liver disease | 0.000 | 0 | 2 | 3 |
| Excl | 22 | Non-alcoholic steatohepatitis | 0.000 | 0 | 3 | 7 |
| Excl | 23 | Contraindication to clopidogrel | 1.000 | 0 | 0 | 0 |
| Excl | 24 | Allergy to clopidogrel | 0.000 | 0 | 7 | 0 |
| Excl | 25 | Active bleeding | 0.000 | 0 | 1 | 0 |
| Excl | 26 | History of intracranial hemorrhage | 1.000 | 0 | 0 | 0 |
| Excl | 27 | Severe hepatic impairment | 1.000 | 0 | 0 | 0 |
| Excl | 28 | Thrombocytopenia | 1.000 | 0 | 0 | 0 |

**gpt-4o vs medgemma-4b**

| Type | # | Ref Description | Jaccard | Shared | Ref-only | Other-only |
|------|---|-----------------|---------|--------|----------|------------|
| Incl | 1 | Age 18 years or older | 1.000 | 0 | 0 | 0 |
| Incl | 2 | Hospitalized for chest pain and poten... | 1.000 | 0 | 0 | 0 |
| Incl | 3 | ST-Elevation Myocardial Infarction (S... | 0.000 | 0 | 1 | 0 |
| Incl | 4 | Non-ST-Elevation Myocardial Infarctio... | 0.000 | 0 | 5 | 0 |
| Incl | 5 | Unstable Angina | 0.000 | 0 | 8 | 0 |
| Incl | 6 | Females of childbearing potential mus... | 0.000 | 0 | 11 | 0 |
| Incl | 7 | Females of childbearing potential mus... | 1.000 | 0 | 0 | 0 |
| Incl | 8 | Use of oral contraceptive pills | 0.000 | 0 | 1 | 0 |
| Incl | 9 | Use of intrauterine device | 0.000 | 0 | 1 | 0 |
| Incl | 10 | Use of contraceptive implant | 0.000 | 0 | 5 | 0 |
| Incl | 11 | Use of contraceptive injection | 0.000 | 0 | 2 | 0 |
| Incl | 12 | Use of barrier method | 0.000 | 0 | 7 | 0 |
| Incl | 13 | Use of sterilization procedure | 0.000 | 0 | 2 | 0 |
| Incl | 14 | ST-segment elevation or new left bund... | 1.000 | 0 | 0 | 0 |
| Incl | 15 | ST-segment elevation | 0.000 | 0 | 3 | 0 |
| Incl | 16 | New left bundle-branch block | 0.000 | 0 | 1 | 0 |
| Excl | 1 | Fibrinolytic therapy within 24 hours | 1.000 | 0 | 0 | 0 |
| Excl | 2 | Alteplase administration | 0.000 | 0 | 2 | 0 |
| Excl | 3 | Reteplase administration | 0.000 | 0 | 1 | 0 |
| Excl | 4 | Tenecteplase administration | 0.000 | 0 | 1 | 0 |
| Excl | 5 | Streptokinase administration | 0.000 | 0 | 2 | 0 |
| Excl | 6 | Urokinase administration | 0.000 | 0 | 1 | 0 |
| Excl | 7 | Treatment with blood clotting agents ... | 1.000 | 0 | 0 | 0 |
| Excl | 8 | Treatment with Factor VIII | 0.000 | 0 | 2 | 0 |
| Excl | 9 | Treatment with Factor IX | 0.000 | 0 | 1 | 0 |
| Excl | 10 | Treatment with Fibrinogen | 0.000 | 0 | 3 | 0 |
| Excl | 11 | Treatment with Prothrombin Complex Co... | 0.000 | 0 | 1 | 0 |
| Excl | 12 | Treatment with Recombinant Factor VIIa | 0.000 | 0 | 1 | 0 |
| Excl | 13 | Invasive procedure for current ACS ep... | 0.000 | 0 | 6 | 0 |
| Excl | 14 | Moderate or severe liver disease | 1.000 | 0 | 0 | 0 |
| Excl | 15 | Cirrhosis of the liver | 0.000 | 0 | 8 | 0 |
| Excl | 16 | Hepatic encephalopathy | 0.000 | 0 | 3 | 0 |
| Excl | 17 | Chronic hepatitis | 0.000 | 0 | 2 | 0 |
| Excl | 18 | Acute liver failure | 0.000 | 0 | 1 | 0 |
| Excl | 19 | Primary biliary cholangitis | 0.000 | 0 | 2 | 0 |
| Excl | 20 | Primary sclerosing cholangitis | 0.000 | 0 | 8 | 0 |
| Excl | 21 | Alcoholic liver disease | 0.000 | 0 | 2 | 0 |
| Excl | 22 | Non-alcoholic steatohepatitis | 0.000 | 0 | 3 | 0 |
| Excl | 23 | Contraindication to clopidogrel | 1.000 | 0 | 0 | 0 |
| Excl | 24 | Allergy to clopidogrel | 0.000 | 0 | 7 | 0 |
| Excl | 25 | Active bleeding | 0.000 | 0 | 1 | 0 |
| Excl | 26 | History of intracranial hemorrhage | 1.000 | 0 | 0 | 0 |
| Excl | 27 | Severe hepatic impairment | 1.000 | 0 | 0 | 0 |
| Excl | 28 | Thrombocytopenia | 1.000 | 0 | 0 | 0 |

## 2. LEADER

### LEADER — Study Metadata

| Model | Study ID | Incl | Excl | HR (95% CI) | Tx N | Comp N |
|-------|----------|------|------|-------------|------|--------|
| gpt-4o | 481 | 35 | 60 | 0.748 (0.607-0.921) | 1150 | 581 |
| medgemma-27b | 523 | 0 | 0 | N/A | 0 | 0 |
| medgemma-4b | 526 | 31 | 32 | 0.666 (0.536-0.827) | 1150 | 581 |

### LEADER — Inclusion Criteria

| # | gpt-4o Description | gpt-4o Concepts | medgemma-27b Description | medgemma-27b Concepts | medgemma-4b Description | medgemma-4b Concepts |
|---|---|---|---|---|---|---|
| 1 | Stenosis >50% of coronary, carotid, or lower extremity ar... | 434961, 442615, 4119613, 4208944 ...+2 | - | - | Liraglutide | 842604, 40170911 |
| 2 | Coronary artery stenosis >50% | 4119613 | - | - | Anti-diabetic drug | - |
| 3 | Carotid artery stenosis >50% | 374371, 442615 | - | - | Type 2 Diabetes Mellitus | 201826 |
| 4 | Lower extremity artery stenosis >50% | 317305, 4208944, 4226026, 4231826 | - | - | Type 1 Diabetes Mellitus | 201254 |
| 5 | Age ≥50 with cardiovascular, cerebrovascular, peripheral ... | - | - | - | Gestational Diabetes Mellitus | 194700, 438480, 4024659, 43531007 |
| 6 | Age ≥60 with other cardiovascular risk factors | - | - | - | Other Diabetes Mellitus | 201820 |
| 7 | Ankle-brachial index <0.9 | 4090814, 40489833, 44805248, 46237026 | - | - | Cv Risk (OR group) | - |
| 8 | Anti-diabetic drug naive or treated with specific drugs | 1513876, 1516976, 35602717 | - | - | Ankle-brachial index | 4090814, 4225712, 40489833, 44805248, 46237026 |
| 9 | Oral anti-diabetic drugs | 40166035, 44785829, 45774751 | - | - | eGFR | 37208635, 37393690, 44791431, 44808279 |
| 10 | Human NPH insulin | 1596977, 46221581 | - | - | Hypertension | 316866 |
| 11 | Long-acting insulin analogue | 1516976, 1586369, 19090221, 19090226 ...+5 | - | - | Microalbuminuria or proteinuria | 75650 |
| 12 | Premixed insulin | 1513876, 1531601 | - | - | Glycated hemoglobin | - |
| 13 | Asymptomatic cardiac ischemia documented by imaging or st... | 4186397, 4199962, 44784440 | - | - | Glycated hemoglobin | 3004410, 4036846, 4184637 |
| 14 | Silent myocardial infarction | 312327, 314666, 439693, 604179 ...+12 | - | - | HbA1c | 3004410, 4184637, 37171451 |
| 15 | Ischemia on stress test | 3037088, 4064926, 4239601 | - | - | Age >= 50 | - |
| 16 | Ischemia on cardiac imaging | 4064926, 4206829, 4225714, 4229709 ...+2 | - | - | Age | 3007191, 3022304, 3023631, 36203531 |
| 17 | Chronic heart failure NYHA class II-III | 444031, 44782713, 44784442 | - | - | Age >= 60 | - |
| 18 | Chronic renal failure | 4128228, 4264718, 46271022 | - | - | Age | 3007191, 3022304, 3023631, 36203531 |
| 19 | HbA1c ≥7.0% | 3003309, 3004410, 3007263 | - | - | Cv Prior (OR group) | - |
| 20 | History of symptomatic CHD | 609191, 1244910, 1340292, 1340513 ...+14 | - | - | Coronary artery stenosis | 4119613 |
| 21 | History of myocardial infarction | 4329847 | - | - | Chronic heart failure | 444031 |
| 22 | History of unstable angina | 608952, 608953, 1340441, 4108670 ...+4 | - | - | Chronic renal failure | 4128228, 4264718, 46271022 |
| 23 | History of stable angina with symptoms | 321318, 4185302 | - | - | Prior MI | 4108218, 4108677, 4119949, 4119950 ...+7 |
| 24 | History of coronary artery bypass grafting (CABG) | 1242650, 4168831, 4231998, 4305852, 4336464 | - | - | Prior coronary, carotid or peripheral arterial revascular... | 312922, 609013, 609015, 763093 ...+4 |
| 25 | History of percutaneous coronary intervention (PCI) | 4216130 | - | - | Prior stroke or TIA | 381316, 4043734, 43530623 |
| 26 | Hypertension with left ventricular hypertrophy | 4184746 | - | - | Asymptomatic cardiac ischemia | 4186397, 4199962, 44784440 |
| 27 | Hypertension | 316866 | - | - | History of symptomatic CHD | - |
| 28 | Left Ventricular Hypertrophy | 4184746 | - | - | Symptomatic Coronary Heart Disease | 316995, 317576, 4134723, 4185932, 40483833 |
| 29 | Left ventricular systolic or diastolic dysfunction | 439846, 442982, 4092936, 4173819, 4323898 | - | - | Left ventricular systolic or diastolic dysfunction | 4323898 |
| 30 | Left ventricular systolic dysfunction | 4047088, 44804772, 44804773 | - | - | Type 2 diabetes | - |
| 31 | Left ventricular diastolic dysfunction | 141038, 4212798, 4253187, 44804772 ...+2 | - | - | Type 2 diabetes | 201826 |
| 32 | Microalbuminuria or proteinuria | 3001802, 3022826, 4020542, 4021120 ...+5 | - | - | - | - |
| 33 | Microalbuminuria | 1175782, 1176069, 1761744, 3000034 ...+15 | - | - | - | - |
| 34 | Proteinuria | 4211845 | - | - | - | - |
| 35 | eGFR <60 mL/min | 37208635, 37393011, 37393012, 37393360 ...+4 | - | - | - | - |

### LEADER — Exclusion Criteria

| # | gpt-4o Description | gpt-4o Concepts | medgemma-27b Description | medgemma-27b Concepts | medgemma-4b Description | medgemma-4b Concepts |
|---|---|---|---|---|---|---|
| 1 | Acute coronary or cerebrovascular event in the previous 1... | 312327, 439693, 604179, 765132 ...+13 | - | - | Acute coronary or cerebrovascular event | 443587, 40486933 |
| 2 | Acute Myocardial Infarction | 4329847 | - | - | Acute decompensation of glycemic control | - |
| 3 | Unstable Angina | 608952, 608953, 1340441, 4108670 ...+4 | - | - | Diabetic Ketoacidosis | 4030520, 4128200, 37017813, 44782717, 45757398 |
| 4 | Ischemic Stroke | 762933, 4045734, 4099974, 4153352 ...+2 | - | - | Hyperosmolar Hyperglycemic State | 609191, 761930, 763093, 3654996 ...+10 |
| 5 | Hemorrhagic Stroke | 376713, 764707, 764721, 35609033 | - | - | Severe Hypoglycemia | 201613, 4064161, 4253211, 4340390 ...+2 |
| 6 | Transient Ischemic Attack | 373503, 374384, 4238191 | - | - | Calcitonin | 24612, 199775 |
| 7 | Acute decompensation of glycemic control | 4029421, 4034965, 4129517, 37311673, 42538715 | - | - | Chronic heart failure | - |
| 8 | Diabetic ketoacidosis | 443727, 761050 | - | - | Heart Failure with Reduced Ejection Fraction | 24612, 4111011, 4112985, 4307263 ...+4 |
| 9 | Hyperosmolar hyperglycemic state | 761049, 4035140, 4147719, 4226238, 42535540 | - | - | Heart Failure with Preserved Ejection Fraction | 25698, 199991, 200906, 257755 ...+11 |
| 10 | Severe hypoglycemia | 1245033, 4034967, 4034968, 4049629 ...+11 | - | - | Current continuous renal replacement therapy | 4127555 |
| 11 | Calcitonin ≥50 ng/L | 4147378 | - | - | Currently planned coronary, carotid, or peripheral artery... | 606747, 1076225, 1244879, 1244903 ...+25 |
| 12 | Chronic heart failure NYHA class IV | 764876, 1245073, 1340281, 4009047 ...+12 | - | - | End-stage liver disease | 4311439 |
| 13 | Current continuous renal replacement therapy | 619390, 4050864, 4120120, 37018292 | - | - | Family or personal history of multiple endocrine neoplasi... | - |
| 14 | Planned coronary, carotid, or peripheral artery revascula... | 4049825, 4216130, 4217445 | - | - | Multiple Endocrine Neoplasia Type 2 | 317510, 4175485, 4186405 |
| 15 | Planned coronary artery revascularization | 1074594, 2001500, 2001504, 4018703 ...+10 | - | - | Familial Medullary Thyroid Carcinoma | 200343, 373152, 440058, 600665 ...+20 |
| 16 | Planned carotid artery revascularization | 602737, 602738, 4019036, 4019038 ...+14 | - | - | History of solid organ transplant or awaiting solid organ... | - |
| 17 | Planned peripheral artery revascularization | 4022319, 4049828, 4052252, 4115340 ...+10 | - | - | Solid organ transplant | 443743 |
| 18 | End-stage liver disease | 201613, 763021, 3655440, 4064161 ...+6 | - | - | Awaiting solid organ transplant | 4111011, 4206181 |
| 19 | Hepatic encephalopathy | 4029488 | - | - | Malignant neoplasm | - |
| 20 | Esophageal varices with bleeding | 22340, 28779, 192671, 4111998 ...+2 | - | - | Carcinoma | 201254 |
| 21 | Hepatorenal syndrome | 196455, 197320, 4026032, 4059281 ...+3 | - | - | Sarcoma | 842604, 40170911 |
| 22 | Ascites | 200528, 4121792, 4154940 | - | - | Leukemia | 793143 |
| 23 | Coagulopathy due to liver disease | 436093, 4028388, 4098766, 4101596 ...+4 | - | - | Lymphoma | 844310, 45774435 |
| 24 | Family or personal history of multiple endocrine neoplasi... | 24612, 1244342, 4111011, 4234784 ...+6 | - | - | Myeloma | 1583722 |
| 25 | Multiple Endocrine Neoplasia Type 2 | 24612, 199775 | - | - | Personal history of non-familial medullary thyroid carcinoma | 1586346, 35602717 |
| 26 | Familial Medullary Thyroid Carcinoma | 24612, 4111011, 4112985, 4307263 ...+4 | - | - | Type 1 diabetes | - |
| 27 | History of solid organ transplant | 25698, 199991, 200906, 257755 ...+10 | - | - | GLP-1 receptor agonist | - |
| 28 | History of kidney transplant | 4128370, 4128371, 4128372, 4309006, 4322471 | - | - | GLP-1 receptor agonist | - |
| 29 | History of liver transplant | 201461, 4076862 | - | - | GLP-1 receptor agonist | - |
| 30 | History of heart transplant | 4137127, 4161515, 4202285, 4309007, 4332085 | - | - | GLP-1 receptor agonist | - |
| 31 | History of lung transplant | 4050878, 4207623, 4337138, 37163742, 44807209 | - | - | GLP-1 receptor agonist | - |
| 32 | History of pancreas transplant | 4266668, 4333225 | - | - | Insulin | - |
| 33 | History of small intestine transplant | 4162772, 4200629, 4201956, 4204157 ...+2 | - | - | - | - |
| 34 | Malignant neoplasm | 607974, 608243, 4031657, 4032806 ...+11 | - | - | - | - |
| 35 | Malignant neoplasm of lung | 443399, 4128888, 4177112, 4247331 ...+3 | - | - | - | - |
| 36 | Malignant neoplasm of breast | 81251 | - | - | - | - |
| 37 | Malignant neoplasm of colon | 443390, 443391, 4180790, 4307687 ...+3 | - | - | - | - |
| 38 | Malignant neoplasm of prostate | 4163261 | - | - | - | - |
| 39 | Malignant neoplasm of pancreas | 4180793 | - | - | - | - |
| 40 | Malignant neoplasm of liver | 197804, 4130518 | - | - | - | - |
| 41 | Malignant neoplasm of stomach | 196044, 197803, 609279, 4094856 ...+21 | - | - | - | - |
| 42 | Malignant neoplasm of esophagus | 4130991, 4181343 | - | - | - | - |
| 43 | Malignant neoplasm of ovary | 4181351 | - | - | - | - |
| 44 | Malignant neoplasm of kidney | 40488919 | - | - | - | - |
| 45 | Malignant neoplasm of bladder | 192855, 197508, 4129897, 4130527 ...+6 | - | - | - | - |
| 46 | Malignant neoplasm of skin | 133974, 139750, 258981, 4110731 ...+21 | - | - | - | - |
| 47 | Malignant neoplasm of brain | 372849, 373152, 373724, 604297 ...+13 | - | - | - | - |
| 48 | Malignant neoplasm of thyroid | 4131909, 4156115 | - | - | - | - |
| 49 | Malignant neoplasm of blood (leukemia) | 132850, 134305, 134603, 135496 ...+12 | - | - | - | - |
| 50 | Malignant neoplasm of lymphatic system (lymphoma) | 200343, 373152, 440058, 600665 ...+19 | - | - | - | - |
| 51 | Type 1 diabetes | 201254 | - | - | - | - |
| 52 | Use of GLP-1 receptor agonist or DPP-4 inhibitor within 3... | 793143, 1583722, 40170911 | - | - | - | - |
| 53 | Use of GLP-1 receptor agonist within 3 months | 1583722, 40170911 | - | - | - | - |
| 54 | Use of DPP-4 inhibitor within 3 months | 1580747 | - | - | - | - |
| 55 | Use of insulin other than specified types within 3 months | 35602717 | - | - | - | - |
| 56 | Use of rapid-acting insulin | 1531601, 1544838, 1586346 | - | - | - | - |
| 57 | Use of intermediate-acting insulin | 1513843, 1513876, 1516976, 1586346 ...+4 | - | - | - | - |
| 58 | Use of ultra-long-acting insulin | 1516976, 1586369, 19090221, 19090226 ...+5 | - | - | - | - |
| 59 | Use of concentrated insulin | 1596977 | - | - | - | - |
| 60 | Use of inhaled insulin | 1588986 | - | - | - | - |

### LEADER — Concept ID Jaccard Similarity (ref: gpt-4o)

**gpt-4o vs medgemma-27b**

| Type | # | Ref Description | Jaccard | Shared | Ref-only | Other-only |
|------|---|-----------------|---------|--------|----------|------------|
| Incl | 1 | Stenosis >50% of coronary, carotid, o... | 0.000 | 0 | 6 | 0 |
| Incl | 2 | Coronary artery stenosis >50% | 0.000 | 0 | 1 | 0 |
| Incl | 3 | Carotid artery stenosis >50% | 0.000 | 0 | 2 | 0 |
| Incl | 4 | Lower extremity artery stenosis >50% | 0.000 | 0 | 4 | 0 |
| Incl | 5 | Age ≥50 with cardiovascular, cerebrov... | 1.000 | 0 | 0 | 0 |
| Incl | 6 | Age ≥60 with other cardiovascular ris... | 1.000 | 0 | 0 | 0 |
| Incl | 7 | Ankle-brachial index <0.9 | 0.000 | 0 | 4 | 0 |
| Incl | 8 | Anti-diabetic drug naive or treated w... | 0.000 | 0 | 3 | 0 |
| Incl | 9 | Oral anti-diabetic drugs | 0.000 | 0 | 3 | 0 |
| Incl | 10 | Human NPH insulin | 0.000 | 0 | 2 | 0 |
| Incl | 11 | Long-acting insulin analogue | 0.000 | 0 | 9 | 0 |
| Incl | 12 | Premixed insulin | 0.000 | 0 | 2 | 0 |
| Incl | 13 | Asymptomatic cardiac ischemia documen... | 0.000 | 0 | 3 | 0 |
| Incl | 14 | Silent myocardial infarction | 0.000 | 0 | 16 | 0 |
| Incl | 15 | Ischemia on stress test | 0.000 | 0 | 3 | 0 |
| Incl | 16 | Ischemia on cardiac imaging | 0.000 | 0 | 6 | 0 |
| Incl | 17 | Chronic heart failure NYHA class II-III | 0.000 | 0 | 3 | 0 |
| Incl | 18 | Chronic renal failure | 0.000 | 0 | 3 | 0 |
| Incl | 19 | HbA1c ≥7.0% | 0.000 | 0 | 3 | 0 |
| Incl | 20 | History of symptomatic CHD | 0.000 | 0 | 18 | 0 |
| Incl | 21 | History of myocardial infarction | 0.000 | 0 | 1 | 0 |
| Incl | 22 | History of unstable angina | 0.000 | 0 | 8 | 0 |
| Incl | 23 | History of stable angina with symptoms | 0.000 | 0 | 2 | 0 |
| Incl | 24 | History of coronary artery bypass gra... | 0.000 | 0 | 5 | 0 |
| Incl | 25 | History of percutaneous coronary inte... | 0.000 | 0 | 1 | 0 |
| Incl | 26 | Hypertension with left ventricular hy... | 0.000 | 0 | 1 | 0 |
| Incl | 27 | Hypertension | 0.000 | 0 | 1 | 0 |
| Incl | 28 | Left Ventricular Hypertrophy | 0.000 | 0 | 1 | 0 |
| Incl | 29 | Left ventricular systolic or diastoli... | 0.000 | 0 | 5 | 0 |
| Incl | 30 | Left ventricular systolic dysfunction | 0.000 | 0 | 3 | 0 |
| Incl | 31 | Left ventricular diastolic dysfunction | 0.000 | 0 | 6 | 0 |
| Incl | 32 | Microalbuminuria or proteinuria | 0.000 | 0 | 9 | 0 |
| Incl | 33 | Microalbuminuria | 0.000 | 0 | 19 | 0 |
| Incl | 34 | Proteinuria | 0.000 | 0 | 1 | 0 |
| Incl | 35 | eGFR <60 mL/min | 0.000 | 0 | 8 | 0 |
| Excl | 1 | Acute coronary or cerebrovascular eve... | 0.000 | 0 | 17 | 0 |
| Excl | 2 | Acute Myocardial Infarction | 0.000 | 0 | 1 | 0 |
| Excl | 3 | Unstable Angina | 0.000 | 0 | 8 | 0 |
| Excl | 4 | Ischemic Stroke | 0.000 | 0 | 6 | 0 |
| Excl | 5 | Hemorrhagic Stroke | 0.000 | 0 | 4 | 0 |
| Excl | 6 | Transient Ischemic Attack | 0.000 | 0 | 3 | 0 |
| Excl | 7 | Acute decompensation of glycemic control | 0.000 | 0 | 5 | 0 |
| Excl | 8 | Diabetic ketoacidosis | 0.000 | 0 | 2 | 0 |
| Excl | 9 | Hyperosmolar hyperglycemic state | 0.000 | 0 | 5 | 0 |
| Excl | 10 | Severe hypoglycemia | 0.000 | 0 | 15 | 0 |
| Excl | 11 | Calcitonin ≥50 ng/L | 0.000 | 0 | 1 | 0 |
| Excl | 12 | Chronic heart failure NYHA class IV | 0.000 | 0 | 16 | 0 |
| Excl | 13 | Current continuous renal replacement ... | 0.000 | 0 | 4 | 0 |
| Excl | 14 | Planned coronary, carotid, or periphe... | 0.000 | 0 | 3 | 0 |
| Excl | 15 | Planned coronary artery revasculariza... | 0.000 | 0 | 14 | 0 |
| Excl | 16 | Planned carotid artery revascularization | 0.000 | 0 | 18 | 0 |
| Excl | 17 | Planned peripheral artery revasculari... | 0.000 | 0 | 14 | 0 |
| Excl | 18 | End-stage liver disease | 0.000 | 0 | 10 | 0 |
| Excl | 19 | Hepatic encephalopathy | 0.000 | 0 | 1 | 0 |
| Excl | 20 | Esophageal varices with bleeding | 0.000 | 0 | 6 | 0 |
| Excl | 21 | Hepatorenal syndrome | 0.000 | 0 | 7 | 0 |
| Excl | 22 | Ascites | 0.000 | 0 | 3 | 0 |
| Excl | 23 | Coagulopathy due to liver disease | 0.000 | 0 | 8 | 0 |
| Excl | 24 | Family or personal history of multipl... | 0.000 | 0 | 10 | 0 |
| Excl | 25 | Multiple Endocrine Neoplasia Type 2 | 0.000 | 0 | 2 | 0 |
| Excl | 26 | Familial Medullary Thyroid Carcinoma | 0.000 | 0 | 8 | 0 |
| Excl | 27 | History of solid organ transplant | 0.000 | 0 | 14 | 0 |
| Excl | 28 | History of kidney transplant | 0.000 | 0 | 5 | 0 |
| Excl | 29 | History of liver transplant | 0.000 | 0 | 2 | 0 |
| Excl | 30 | History of heart transplant | 0.000 | 0 | 5 | 0 |
| Excl | 31 | History of lung transplant | 0.000 | 0 | 5 | 0 |
| Excl | 32 | History of pancreas transplant | 0.000 | 0 | 2 | 0 |
| Excl | 33 | History of small intestine transplant | 0.000 | 0 | 6 | 0 |
| Excl | 34 | Malignant neoplasm | 0.000 | 0 | 15 | 0 |
| Excl | 35 | Malignant neoplasm of lung | 0.000 | 0 | 7 | 0 |
| Excl | 36 | Malignant neoplasm of breast | 0.000 | 0 | 1 | 0 |
| Excl | 37 | Malignant neoplasm of colon | 0.000 | 0 | 7 | 0 |
| Excl | 38 | Malignant neoplasm of prostate | 0.000 | 0 | 1 | 0 |
| Excl | 39 | Malignant neoplasm of pancreas | 0.000 | 0 | 1 | 0 |
| Excl | 40 | Malignant neoplasm of liver | 0.000 | 0 | 2 | 0 |
| Excl | 41 | Malignant neoplasm of stomach | 0.000 | 0 | 25 | 0 |
| Excl | 42 | Malignant neoplasm of esophagus | 0.000 | 0 | 2 | 0 |
| Excl | 43 | Malignant neoplasm of ovary | 0.000 | 0 | 1 | 0 |
| Excl | 44 | Malignant neoplasm of kidney | 0.000 | 0 | 1 | 0 |
| Excl | 45 | Malignant neoplasm of bladder | 0.000 | 0 | 10 | 0 |
| Excl | 46 | Malignant neoplasm of skin | 0.000 | 0 | 25 | 0 |
| Excl | 47 | Malignant neoplasm of brain | 0.000 | 0 | 17 | 0 |
| Excl | 48 | Malignant neoplasm of thyroid | 0.000 | 0 | 2 | 0 |
| Excl | 49 | Malignant neoplasm of blood (leukemia) | 0.000 | 0 | 16 | 0 |
| Excl | 50 | Malignant neoplasm of lymphatic syste... | 0.000 | 0 | 23 | 0 |
| Excl | 51 | Type 1 diabetes | 0.000 | 0 | 1 | 0 |
| Excl | 52 | Use of GLP-1 receptor agonist or DPP-... | 0.000 | 0 | 3 | 0 |
| Excl | 53 | Use of GLP-1 receptor agonist within ... | 0.000 | 0 | 2 | 0 |
| Excl | 54 | Use of DPP-4 inhibitor within 3 months | 0.000 | 0 | 1 | 0 |
| Excl | 55 | Use of insulin other than specified t... | 0.000 | 0 | 1 | 0 |
| Excl | 56 | Use of rapid-acting insulin | 0.000 | 0 | 3 | 0 |
| Excl | 57 | Use of intermediate-acting insulin | 0.000 | 0 | 8 | 0 |
| Excl | 58 | Use of ultra-long-acting insulin | 0.000 | 0 | 9 | 0 |
| Excl | 59 | Use of concentrated insulin | 0.000 | 0 | 1 | 0 |
| Excl | 60 | Use of inhaled insulin | 0.000 | 0 | 1 | 0 |

**gpt-4o vs medgemma-4b**

| Type | # | Ref Description | Jaccard | Shared | Ref-only | Other-only |
|------|---|-----------------|---------|--------|----------|------------|
| Incl | 1 | Stenosis >50% of coronary, carotid, o... | 0.000 | 0 | 6 | 2 |
| Incl | 2 | Coronary artery stenosis >50% | 0.000 | 0 | 1 | 0 |
| Incl | 3 | Carotid artery stenosis >50% | 0.000 | 0 | 2 | 1 |
| Incl | 4 | Lower extremity artery stenosis >50% | 0.000 | 0 | 4 | 1 |
| Incl | 5 | Age ≥50 with cardiovascular, cerebrov... | 0.000 | 0 | 0 | 4 |
| Incl | 6 | Age ≥60 with other cardiovascular ris... | 0.000 | 0 | 0 | 1 |
| Incl | 7 | Ankle-brachial index <0.9 | 0.000 | 0 | 4 | 0 |
| Incl | 8 | Anti-diabetic drug naive or treated w... | 0.000 | 0 | 3 | 5 |
| Incl | 9 | Oral anti-diabetic drugs | 0.000 | 0 | 3 | 4 |
| Incl | 10 | Human NPH insulin | 0.000 | 0 | 2 | 1 |
| Incl | 11 | Long-acting insulin analogue | 0.000 | 0 | 9 | 1 |
| Incl | 12 | Premixed insulin | 0.000 | 0 | 2 | 0 |
| Incl | 13 | Asymptomatic cardiac ischemia documen... | 0.000 | 0 | 3 | 3 |
| Incl | 14 | Silent myocardial infarction | 0.000 | 0 | 16 | 3 |
| Incl | 15 | Ischemia on stress test | 0.000 | 0 | 3 | 0 |
| Incl | 16 | Ischemia on cardiac imaging | 0.000 | 0 | 6 | 4 |
| Incl | 17 | Chronic heart failure NYHA class II-III | 0.000 | 0 | 3 | 0 |
| Incl | 18 | Chronic renal failure | 0.000 | 0 | 3 | 4 |
| Incl | 19 | HbA1c ≥7.0% | 0.000 | 0 | 3 | 0 |
| Incl | 20 | History of symptomatic CHD | 0.000 | 0 | 18 | 1 |
| Incl | 21 | History of myocardial infarction | 0.000 | 0 | 1 | 1 |
| Incl | 22 | History of unstable angina | 0.000 | 0 | 8 | 3 |
| Incl | 23 | History of stable angina with symptoms | 0.000 | 0 | 2 | 11 |
| Incl | 24 | History of coronary artery bypass gra... | 0.000 | 0 | 5 | 8 |
| Incl | 25 | History of percutaneous coronary inte... | 0.000 | 0 | 1 | 3 |
| Incl | 26 | Hypertension with left ventricular hy... | 0.000 | 0 | 1 | 3 |
| Incl | 27 | Hypertension | 0.000 | 0 | 1 | 0 |
| Incl | 28 | Left Ventricular Hypertrophy | 0.000 | 0 | 1 | 5 |
| Incl | 29 | Left ventricular systolic or diastoli... | 0.200 | 1 | 4 | 0 |
| Incl | 30 | Left ventricular systolic dysfunction | 0.000 | 0 | 3 | 0 |
| Incl | 31 | Left ventricular diastolic dysfunction | 0.000 | 0 | 6 | 1 |
| Incl | 32 | Microalbuminuria or proteinuria | 0.000 | 0 | 9 | 0 |
| Incl | 33 | Microalbuminuria | 0.000 | 0 | 19 | 0 |
| Incl | 34 | Proteinuria | 0.000 | 0 | 1 | 0 |
| Incl | 35 | eGFR <60 mL/min | 0.000 | 0 | 8 | 0 |
| Excl | 1 | Acute coronary or cerebrovascular eve... | 0.000 | 0 | 17 | 2 |
| Excl | 2 | Acute Myocardial Infarction | 0.000 | 0 | 1 | 0 |
| Excl | 3 | Unstable Angina | 0.000 | 0 | 8 | 5 |
| Excl | 4 | Ischemic Stroke | 0.000 | 0 | 6 | 14 |
| Excl | 5 | Hemorrhagic Stroke | 0.000 | 0 | 4 | 6 |
| Excl | 6 | Transient Ischemic Attack | 0.000 | 0 | 3 | 2 |
| Excl | 7 | Acute decompensation of glycemic control | 0.000 | 0 | 5 | 0 |
| Excl | 8 | Diabetic ketoacidosis | 0.000 | 0 | 2 | 8 |
| Excl | 9 | Hyperosmolar hyperglycemic state | 0.000 | 0 | 5 | 15 |
| Excl | 10 | Severe hypoglycemia | 0.000 | 0 | 15 | 1 |
| Excl | 11 | Calcitonin ≥50 ng/L | 0.000 | 0 | 1 | 29 |
| Excl | 12 | Chronic heart failure NYHA class IV | 0.000 | 0 | 16 | 1 |
| Excl | 13 | Current continuous renal replacement ... | 0.000 | 0 | 4 | 0 |
| Excl | 14 | Planned coronary, carotid, or periphe... | 0.000 | 0 | 3 | 3 |
| Excl | 15 | Planned coronary artery revasculariza... | 0.000 | 0 | 14 | 24 |
| Excl | 16 | Planned carotid artery revascularization | 0.000 | 0 | 18 | 0 |
| Excl | 17 | Planned peripheral artery revasculari... | 0.000 | 0 | 14 | 1 |
| Excl | 18 | End-stage liver disease | 0.000 | 0 | 10 | 2 |
| Excl | 19 | Hepatic encephalopathy | 0.000 | 0 | 1 | 0 |
| Excl | 20 | Esophageal varices with bleeding | 0.000 | 0 | 6 | 1 |
| Excl | 21 | Hepatorenal syndrome | 0.000 | 0 | 7 | 2 |
| Excl | 22 | Ascites | 0.000 | 0 | 3 | 1 |
| Excl | 23 | Coagulopathy due to liver disease | 0.000 | 0 | 8 | 2 |
| Excl | 24 | Family or personal history of multipl... | 0.000 | 0 | 10 | 1 |
| Excl | 25 | Multiple Endocrine Neoplasia Type 2 | 0.000 | 0 | 2 | 2 |
| Excl | 26 | Familial Medullary Thyroid Carcinoma | 0.000 | 0 | 8 | 0 |
| Excl | 27 | History of solid organ transplant | 0.000 | 0 | 14 | 0 |
| Excl | 28 | History of kidney transplant | 0.000 | 0 | 5 | 0 |
| Excl | 29 | History of liver transplant | 0.000 | 0 | 2 | 0 |
| Excl | 30 | History of heart transplant | 0.000 | 0 | 5 | 0 |
| Excl | 31 | History of lung transplant | 0.000 | 0 | 5 | 0 |
| Excl | 32 | History of pancreas transplant | 0.000 | 0 | 2 | 0 |
| Excl | 33 | History of small intestine transplant | 0.000 | 0 | 6 | 0 |
| Excl | 34 | Malignant neoplasm | 0.000 | 0 | 15 | 0 |
| Excl | 35 | Malignant neoplasm of lung | 0.000 | 0 | 7 | 0 |
| Excl | 36 | Malignant neoplasm of breast | 0.000 | 0 | 1 | 0 |
| Excl | 37 | Malignant neoplasm of colon | 0.000 | 0 | 7 | 0 |
| Excl | 38 | Malignant neoplasm of prostate | 0.000 | 0 | 1 | 0 |
| Excl | 39 | Malignant neoplasm of pancreas | 0.000 | 0 | 1 | 0 |
| Excl | 40 | Malignant neoplasm of liver | 0.000 | 0 | 2 | 0 |
| Excl | 41 | Malignant neoplasm of stomach | 0.000 | 0 | 25 | 0 |
| Excl | 42 | Malignant neoplasm of esophagus | 0.000 | 0 | 2 | 0 |
| Excl | 43 | Malignant neoplasm of ovary | 0.000 | 0 | 1 | 0 |
| Excl | 44 | Malignant neoplasm of kidney | 0.000 | 0 | 1 | 0 |
| Excl | 45 | Malignant neoplasm of bladder | 0.000 | 0 | 10 | 0 |
| Excl | 46 | Malignant neoplasm of skin | 0.000 | 0 | 25 | 0 |
| Excl | 47 | Malignant neoplasm of brain | 0.000 | 0 | 17 | 0 |
| Excl | 48 | Malignant neoplasm of thyroid | 0.000 | 0 | 2 | 0 |
| Excl | 49 | Malignant neoplasm of blood (leukemia) | 0.000 | 0 | 16 | 0 |
| Excl | 50 | Malignant neoplasm of lymphatic syste... | 0.000 | 0 | 23 | 0 |
| Excl | 51 | Type 1 diabetes | 0.000 | 0 | 1 | 0 |
| Excl | 52 | Use of GLP-1 receptor agonist or DPP-... | 0.000 | 0 | 3 | 0 |
| Excl | 53 | Use of GLP-1 receptor agonist within ... | 0.000 | 0 | 2 | 0 |
| Excl | 54 | Use of DPP-4 inhibitor within 3 months | 0.000 | 0 | 1 | 0 |
| Excl | 55 | Use of insulin other than specified t... | 0.000 | 0 | 1 | 0 |
| Excl | 56 | Use of rapid-acting insulin | 0.000 | 0 | 3 | 0 |
| Excl | 57 | Use of intermediate-acting insulin | 0.000 | 0 | 8 | 0 |
| Excl | 58 | Use of ultra-long-acting insulin | 0.000 | 0 | 9 | 0 |
| Excl | 59 | Use of concentrated insulin | 0.000 | 0 | 1 | 0 |
| Excl | 60 | Use of inhaled insulin | 0.000 | 0 | 1 | 0 |

## 2. ARISTOTLE

### ARISTOTLE — Study Metadata

| Model | Study ID | Incl | Excl | HR (95% CI) | Tx N | Comp N |
|-------|----------|------|------|-------------|------|--------|
| gpt-4o | 482 | 13 | 19 | 1.418 (0.772-2.606) | 875 | 2305 |
| medgemma-27b | 524 | 13 | 29 | 1.706 (0.898-3.239) | 875 | 2305 |
| medgemma-4b | 527 | 17 | 21 | 1.706 (0.898-3.239) | 875 | 2305 |

### ARISTOTLE — Inclusion Criteria

| # | gpt-4o Description | gpt-4o Concepts | medgemma-27b Description | medgemma-27b Concepts | medgemma-4b Description | medgemma-4b Concepts |
|---|---|---|---|---|---|---|
| 1 | Atrial fibrillation or atrial flutter | - | Age >= 18 | - | Age ≥ 18 yrs | - |
| 2 | Atrial fibrillation | 313217, 42689664 | Atrial Fibrillation | 313217, 42689664 | Age | 3007191, 3022304, 3023631, 36203531 |
| 3 | Atrial flutter | 314665, 4111700, 42536725 | Atrial Flutter | 314665, 4111700, 42536725 | Atrial Fibrillation | 313217, 42689664 |
| 4 | Age ≥ 18 years | - | Stroke Risk Factors | - | One or more risk factors for stroke | - |
| 5 | Stroke risk factors (composite) | - | Age >= 75 | - | Age ≥ 75 yrs | 4121339 |
| 6 | Age ≥ 75 years | - | Previous Stroke | 381316, 443454 | Previous Stroke | 381316, 40479575, 40480002, 40480449 ...+10 |
| 7 | Previous stroke | 381316, 443454 | Diabetes Mellitus | 201820 | Diabetes Mellitus | 201820 |
| 8 | Diabetes mellitus requiring treatment | 201820 | Hypertension | 316866 | Hypertension | 316866 |
| 9 | Hypertension requiring treatment | 316866 | Congestive Heart Failure | 319835 | Symptomatic Congestive Heart Failure | 319835, 442310, 443580, 443587, 444031 |
| 10 | Symptomatic congestive heart failure | 316139 | Left Ventricular Dysfunction | 439846, 442982, 4092936, 4143971 ...+3 | Left Ventricular Ejection Fraction ≤ 40% | 319835, 439846, 443580, 443587 ...+6 |
| 11 | Left ventricular dysfunction (LVEF ≤ 40%) | 3027172, 4239905, 4290536, 40758535 | LVEF <= 40% | 3027172, 4239905, 4313573, 40758535 | Warfarin dose adjustment algorithm | 1247038, 4008971, 4094890, 4097737 ...+5 |
| 12 | Transient ischemic attack (TIA) | 373503, 374384, 4238191 | Transient Ischemic Attack | 373503, 374384, 4238191 | Cardiovascular death | 319844, 321042, 442310, 604179 ...+3 |
| 13 | Systemic embolism | 4185607 | Systemic Embolism | 4185607 | Major Bleeding | 4010901, 4134158, 4170068, 36712677, 40488840 |
| 14 | - | - | - | - | Double-dummy design | 4208617 |
| 15 | - | - | - | - | Encrypted point-of-care international normalized ratio de... | 762519, 764288, 764339, 764340 ...+3 |
| 16 | - | - | - | - | Transient Ischemic Attack or Systemic Embolism | 4048785, 4139517, 4185607, 37163288 ...+2 |
| 17 | - | - | - | - | TIA or SE | 4048785, 4139517, 4185607, 37163288 ...+2 |

### ARISTOTLE — Exclusion Criteria

| # | gpt-4o Description | gpt-4o Concepts | medgemma-27b Description | medgemma-27b Concepts | medgemma-4b Description | medgemma-4b Concepts |
|---|---|---|---|---|---|---|
| 1 | Conditions requiring anticoagulation other than AF | 313217, 435983, 4104431, 37208159 | AF attributable to reversible cause | - | Biomarker program participation | 1247038, 4008971, 4094890, 4097737 ...+5 |
| 2 | Atrial fibrillation attributable to a reversible cause | - | AF attributable to hyperthyroidism | 313217, 440417, 762808, 4124696, 4171269 | Warfarin dose adjustment algorithm | 319844, 321042, 442310, 604179 ...+3 |
| 3 | Atrial fibrillation due to hyperthyroidism | 313217, 438172, 609068, 609083 ...+3 | AF attributable to pulmonary embolism | 1340258, 4117112, 4119601, 4119602 ...+10 | Cardiovascular death | 314667, 761790, 4045734, 4099974 ...+8 |
| 4 | Atrial fibrillation due to alcohol intoxication | 313217, 440417, 762808, 4120084 ...+2 | AF attributable to pericarditis | 314383, 4119601, 4119602, 4141360 ...+4 | Non-AF anticoagulation need | 316866 |
| 5 | Atrial fibrillation due to acute myocardial infarction | 607321, 37018498, 40486058, 40486685 ...+5 | AF attributable to myocarditis | 312327, 313217, 317302, 609068 ...+9 | Reversible AF cause | - |
| 6 | Atrial fibrillation due to pulmonary embolism | 313217, 441830 | AF attributable to acute coronary syndrome | 37171038 | Absence of Hypertension | 138387, 4142479 |
| 7 | Atrial fibrillation due to sepsis | 315273 | AF attributable to valvular heart disease | 313217, 441830 | Absence of Hyperthyroidism | 440417 |
| 8 | Atrial fibrillation due to electrolyte imbalance | 1112807, 1134439 | AF attributable to electrolyte imbalance | 313217, 435983, 4104431, 37208159 | Absence of Pulmonary Embolism | 432456, 1469511, 4027343, 4176651 |
| 9 | Moderate or severe mitral stenosis | 1112807, 1322184 | AF attributable to alcohol intoxication | 313217, 4121463, 37151414 | Absence of Alcohol use | 441830 |
| 10 | Need for aspirin > 165 mg/day or both aspirin and clopido... | - | AF attributable to post-operative state | 607321, 37018498, 40486058, 40486685 ...+5 | Absence of Electrolyte imbalance | 137977, 4040710, 4134158, 4166729 ...+6 |
| 11 | High-dose aspirin requirement | 3016723, 3020564, 4013964, 40484175, 46235076 | AF attributable to sepsis | 255848, 313217, 1075640, 3655111 ...+10 | Absence of Acute illness | 4208617 |
| 12 | Concurrent use of aspirin and clopidogrel | 4042762, 37393359, 40282772 | AF attributable to pneumonia | 1340258, 4117112, 4119593, 4119601 ...+8 | Double-dummy design | 4203780 |
| 13 | Severe renal insufficiency (serum creatinine > 2.5 mg/dL) | 762933, 4045734, 4099974, 4153352 ...+2 | AF attributable to drug use | 315273 | Random assignment | 762519, 764288, 764339, 764340 ...+3 |
| 14 | Severe renal insufficiency (creatinine clearance < 25 mL/... | 376713, 764707, 764721, 35609033 | Moderate or severe mitral stenosis | - | Encrypted point-of-care international normalized ratio de... | 315273 |
| 15 | Stroke within 7 days | - | Moderate mitral stenosis | 315273 | Moderate or severe mitral stenosis | 436529, 4135466, 4155911, 4209571 ...+7 |
| 16 | Ischemic Stroke | 373503, 374384, 4238191 | Severe mitral stenosis | 19018432, 19084912 | Aspirin or Clopidogrel use | - |
| 17 | Hemorrhagic Stroke | 603326, 4046363, 4099974, 4189462 ...+8 | Need for aspirin >165 mg/d | 19018432, 19084912 | Aspirin use | 4069584, 4222080 |
| 18 | Transient Ischemic Attack (TIA) | - | Need for aspirin and clopidogrel | - | Clopidogrel use | 4022693, 4113696, 4118830, 4136121 |
| 19 | Cryptogenic Stroke | - | Aspirin | 1322184 | CysC measurements available | 192359, 443611, 36716945 |
| 20 | - | - | Clopidogrel | 3016723, 3020564, 4013964, 40484175, 46235076 | Severe renal insufficiency | 372654, 764707, 764721, 4099974 ...+14 |
| 21 | - | - | Severe renal insufficiency | - | Stroke within 7 days | - |
| 22 | - | - | Serum Creatinine > 2.5 mg/dL | 4042762, 37393359, 40282772 | - | - |
| 23 | - | - | Calculated Creatinine Clearance < 25 mL/min | 603206, 762933, 763009, 4045734 ...+13 | - | - |
| 24 | - | - | Stroke within 7 days | - | - | - |
| 25 | - | - | Ischemic Stroke | 376713, 764707, 764721, 35609033 | - | - |
| 26 | - | - | Hemorrhagic Stroke | 381316 | - | - |
| 27 | - | - | Unspecified Stroke | 435616, 440417, 444247, 4078700 ...+14 | - | - |
| 28 | - | - | Anticoagulation required for other conditions | 142026 | - | - |
| 29 | - | - | Prosthetic heart valve | - | - | - |

### ARISTOTLE — Concept ID Jaccard Similarity (ref: gpt-4o)

**gpt-4o vs medgemma-27b**

| Type | # | Ref Description | Jaccard | Shared | Ref-only | Other-only |
|------|---|-----------------|---------|--------|----------|------------|
| Incl | 1 | Atrial fibrillation or atrial flutter | 1.000 | 0 | 0 | 0 |
| Incl | 2 | Atrial fibrillation | 1.000 | 2 | 0 | 0 |
| Incl | 3 | Atrial flutter | 1.000 | 3 | 0 | 0 |
| Incl | 4 | Age ≥ 18 years | 1.000 | 0 | 0 | 0 |
| Incl | 5 | Stroke risk factors (composite) | 1.000 | 0 | 0 | 0 |
| Incl | 6 | Age ≥ 75 years | 0.000 | 0 | 0 | 2 |
| Incl | 7 | Previous stroke | 0.000 | 0 | 2 | 1 |
| Incl | 8 | Diabetes mellitus requiring treatment | 0.000 | 0 | 1 | 1 |
| Incl | 9 | Hypertension requiring treatment | 0.000 | 0 | 1 | 1 |
| Incl | 10 | Symptomatic congestive heart failure | 0.000 | 0 | 1 | 7 |
| Incl | 11 | Left ventricular dysfunction (LVEF ≤ ... | 0.600 | 3 | 1 | 1 |
| Incl | 12 | Transient ischemic attack (TIA) | 1.000 | 3 | 0 | 0 |
| Incl | 13 | Systemic embolism | 1.000 | 1 | 0 | 0 |
| Excl | 1 | Conditions requiring anticoagulation ... | 0.000 | 0 | 4 | 0 |
| Excl | 2 | Atrial fibrillation attributable to a... | 0.000 | 0 | 0 | 5 |
| Excl | 3 | Atrial fibrillation due to hyperthyro... | 0.000 | 0 | 7 | 14 |
| Excl | 4 | Atrial fibrillation due to alcohol in... | 0.000 | 0 | 6 | 8 |
| Excl | 5 | Atrial fibrillation due to acute myoc... | 0.000 | 0 | 9 | 13 |
| Excl | 6 | Atrial fibrillation due to pulmonary ... | 0.000 | 0 | 2 | 1 |
| Excl | 7 | Atrial fibrillation due to sepsis | 0.000 | 0 | 1 | 2 |
| Excl | 8 | Atrial fibrillation due to electrolyt... | 0.000 | 0 | 2 | 4 |
| Excl | 9 | Moderate or severe mitral stenosis | 0.000 | 0 | 2 | 3 |
| Excl | 10 | Need for aspirin > 165 mg/day or both... | 0.000 | 0 | 0 | 9 |
| Excl | 11 | High-dose aspirin requirement | 0.000 | 0 | 5 | 14 |
| Excl | 12 | Concurrent use of aspirin and clopido... | 0.000 | 0 | 3 | 12 |
| Excl | 13 | Severe renal insufficiency (serum cre... | 0.000 | 0 | 6 | 1 |
| Excl | 14 | Severe renal insufficiency (creatinin... | 0.000 | 0 | 4 | 0 |
| Excl | 15 | Stroke within 7 days | 0.000 | 0 | 0 | 1 |
| Excl | 16 | Ischemic Stroke | 0.000 | 0 | 3 | 2 |
| Excl | 17 | Hemorrhagic Stroke | 0.000 | 0 | 12 | 2 |
| Excl | 18 | Transient Ischemic Attack (TIA) | 1.000 | 0 | 0 | 0 |
| Excl | 19 | Cryptogenic Stroke | 0.000 | 0 | 0 | 1 |

**gpt-4o vs medgemma-4b**

| Type | # | Ref Description | Jaccard | Shared | Ref-only | Other-only |
|------|---|-----------------|---------|--------|----------|------------|
| Incl | 1 | Atrial fibrillation or atrial flutter | 1.000 | 0 | 0 | 0 |
| Incl | 2 | Atrial fibrillation | 0.000 | 0 | 2 | 4 |
| Incl | 3 | Atrial flutter | 0.000 | 0 | 3 | 2 |
| Incl | 4 | Age ≥ 18 years | 1.000 | 0 | 0 | 0 |
| Incl | 5 | Stroke risk factors (composite) | 0.000 | 0 | 0 | 1 |
| Incl | 6 | Age ≥ 75 years | 0.000 | 0 | 0 | 14 |
| Incl | 7 | Previous stroke | 0.000 | 0 | 2 | 1 |
| Incl | 8 | Diabetes mellitus requiring treatment | 0.000 | 0 | 1 | 1 |
| Incl | 9 | Hypertension requiring treatment | 0.000 | 0 | 1 | 5 |
| Incl | 10 | Symptomatic congestive heart failure | 0.000 | 0 | 1 | 10 |
| Incl | 11 | Left ventricular dysfunction (LVEF ≤ ... | 0.000 | 0 | 4 | 9 |
| Incl | 12 | Transient ischemic attack (TIA) | 0.000 | 0 | 3 | 7 |
| Incl | 13 | Systemic embolism | 0.000 | 0 | 1 | 5 |
| Excl | 1 | Conditions requiring anticoagulation ... | 0.000 | 0 | 4 | 9 |
| Excl | 2 | Atrial fibrillation attributable to a... | 0.000 | 0 | 0 | 7 |
| Excl | 3 | Atrial fibrillation due to hyperthyro... | 0.000 | 0 | 7 | 12 |
| Excl | 4 | Atrial fibrillation due to alcohol in... | 0.000 | 0 | 6 | 1 |
| Excl | 5 | Atrial fibrillation due to acute myoc... | 0.000 | 0 | 9 | 0 |
| Excl | 6 | Atrial fibrillation due to pulmonary ... | 0.000 | 0 | 2 | 2 |
| Excl | 7 | Atrial fibrillation due to sepsis | 0.000 | 0 | 1 | 1 |
| Excl | 8 | Atrial fibrillation due to electrolyt... | 0.000 | 0 | 2 | 4 |
| Excl | 9 | Moderate or severe mitral stenosis | 0.000 | 0 | 2 | 1 |
| Excl | 10 | Need for aspirin > 165 mg/day or both... | 0.000 | 0 | 0 | 10 |
| Excl | 11 | High-dose aspirin requirement | 0.000 | 0 | 5 | 1 |
| Excl | 12 | Concurrent use of aspirin and clopido... | 0.000 | 0 | 3 | 1 |
| Excl | 13 | Severe renal insufficiency (serum cre... | 0.000 | 0 | 6 | 7 |
| Excl | 14 | Severe renal insufficiency (creatinin... | 0.000 | 0 | 4 | 1 |
| Excl | 15 | Stroke within 7 days | 0.000 | 0 | 0 | 11 |
| Excl | 16 | Ischemic Stroke | 0.000 | 0 | 3 | 0 |
| Excl | 17 | Hemorrhagic Stroke | 0.000 | 0 | 12 | 2 |
| Excl | 18 | Transient Ischemic Attack (TIA) | 0.000 | 0 | 0 | 4 |
| Excl | 19 | Cryptogenic Stroke | 0.000 | 0 | 0 | 3 |

## 3. Study ID Reference

| Model | PLATO | LEADER | ARISTOTLE |
|-------|-------|--------|----------|
| gpt-4o | 480 | 481 | 482 |
| medgemma-27b | 522 | 523 | 524 |
| medgemma-4b | 525 | 526 | 527 |

