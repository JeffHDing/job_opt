## 1. Match Analysis

- `Covered:`
    - Python/ML libraries — "Technical Skills" section, "Maternal Health Risk Classifier" project.
    - Production-quality code/APIs — "Filesystem Organizing API" project.
    - EDA/Data Analysis — "Sunnybrook Research Institute" bullets, "Projects" section.
- `Missing or weak:`
    - Large-scale data warehousing (BigQuery/Redshift) — Not mentioned.
    - Real-time/Low-latency production systems — Not mentioned.
    - A/B testing/Experimental design — Not mentioned.
    - Fraud/Risk domain experience — Not mentioned.
    - 3+ years of industry experience — Resume shows ~2 years of relevant experience; current role is a mentorship/volunteer position.

## 2. Quantification Gaps

- `Original:` Performed regression on open-source data to correlate comorbidities and clinical trial participation.
- `Rewrite:` Performed regression analysis on [N] records to identify [X]% correlation between comorbidities and clinical trial participation.
- `Original:` Preprocessed and analyzed retina scans utilizing a Convolutional Neural Network (CNN) and Residual blocks using Keras and TensorFlow 2.0 to improve early detection of retinopathy.
- `Rewrite:` Developed a CNN with Residual blocks achieving [X]% accuracy and [Y]% reduction in false negatives for early-stage diabetic retinopathy detection.
- `Original:` Published a Jupyter notebook that visualizes time-series stock data from Yahoo! Finance using dynamic figures.
- `Rewrite:` Built a time-series dashboard processing [N] years of financial data, reducing analysis time for [Target Audience] by [X]%.

## 3. Keyword Gaps

- `Missing:` BigQuery, Redshift, A/B testing, causal inference, Docker, XGBoost, Tableau, Looker, Kafka, Flink, MLflow.
- `Underused:` SQL (only in Skills; needs to be in an Experience bullet), Production (needs to be explicitly linked to model deployment), Deployment (needs to be in an Experience bullet).

## 4. STAR Rewrites — Top 3 Weakest Bullets

- `Original:` Partnered with researchers as a volunteer clinical research coordinator consultant.
- `Situation:` Research team lacked automated pipelines for clinical data analysis.
- `Task:` Improve data processing efficiency for ongoing studies.
- `Action:` Built automated Python scripts to clean and structure raw clinical datasets.
- `Result:` Reduced manual data entry time by [X]% for [N] researchers.
- `Rewritten bullet:` Engineered automated Python data pipelines to process clinical research datasets, reducing manual data entry time by [X]% for [N] researchers.

- `Original:` Orchestrated the simultaneous conduct of 15+ clinical trials by coordinating cross-functional teams.
- `Situation:` High volume of concurrent clinical trials required strict adherence to regulatory timelines.
- `Task:` Manage project lifecycles and cross-functional dependencies.
- `Action:` Implemented a centralized tracking system for trial milestones and stakeholder communication.
- `Result:` Maintained 100% compliance across [N] trials while accelerating activation by [X]%.
- `Rewritten bullet:` Orchestrated 15+ concurrent clinical trials by implementing a centralized tracking system, ensuring 100% regulatory compliance and accelerating trial activation by [X]%.

- `Original:` Investigated provincial healthcare data to optimize the transition of cancer survivors to primary care.
- `Situation:` High volume of cancer survivors lacking structured transition plans.
- `Task:` Identify patterns in healthcare data to improve patient outcomes.
- `Action:` Performed exploratory data analysis (EDA) on [N] records to identify key transition bottlenecks.
- `Result:` Provided insights that informed [Policy/Process] changes, impacting [N] patients.
- `Rewritten bullet:` Conducted EDA on [N] provincial healthcare records to identify patient transition bottlenecks, providing actionable insights that improved care continuity for [N] cancer survivors.

## 5. ATS Optimization

- `Section Naming:` Rename "Technical Skills" to "Technical Proficiencies" and group by category (e.g., "Languages & Databases," "ML & Frameworks," "Cloud & Tools").
- `Keyword Density:` You are missing critical infrastructure keywords. Add a "Projects" or "Experience" bullet that explicitly mentions "deploying models via Docker" or "querying BigQuery/SQL."
- `Experience Formatting:` Your current experience is heavily clinical. You must reframe the "Data Manager" role to emphasize the *technical* aspects (SQL, data cleaning, pipeline management) rather than the *administrative* aspects (liaising, submissions).
- `File Structure:` Ensure the resume is in a clean, single-column format. Remove all icons/links that aren't plain text URLs to ensure the parser doesn't choke on non-text elements.

## 6. Top 5 Priorities

1. **Quantify your impact:** Every bullet in your "Experience" section must have a metric (%, N, or time saved) or it will be ignored by the recruiter.
2. **Bridge the domain gap:** Re-write your Sunnybrook bullets to emphasize "data pipelines," "SQL," and "automated analysis" rather than "coordinating teams."
3. **Add missing stack:** Explicitly add "SQL," "Docker," and "XGBoost" to your Experience section bullets, not just the Skills list.
4. **Highlight A/B testing:** Add a bullet to your "Maternal Health" or "Retinopathy" project describing how you validated your model (e.g., "Validated model performance using a hold-out test set and simulated A/B testing framework").
5. **Address the 3-year requirement:** If you have any other relevant work or internships, add them. If not, emphasize the *depth* of your technical projects to compensate for the lack of industry tenure.