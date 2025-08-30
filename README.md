# JARVIS: Jenkins Agent for Retry, Validation & Intelligent Summary

**JARVIS** is an AI-powered agent designed to supercharge CI/CD pipelines by automatically diagnosing, classifying, and intelligently healing test failures in Jenkins. Leveraging state-of-the-art LLMs (e.g., GPT-4o-mini), JARVIS helps teams save time, reduce noise, and focus on what matters most: building high-quality software.

---

## 🚀 Core Features

- **AI-Powered Triage**  
  Instantly diagnoses and categorizes test failures (e.g., code bugs, infrastructure issues, flaky tests, data problems) using advanced LLMs.
  
- **Intelligent Retry**  
  Automatically reruns only those tests identified as transient or “retry-worthy,” minimizing manual intervention and CI pipeline noise.

- **Root-Cause Insights (Planned)**  
  Provides actionable recommendations and summaries to resolve failures faster and reduce recurring issues.

- **Self-Healing (Planned)**  
  Will suggest or auto-generate code/config fixes for common issues in future versions.

- **Rich Analytics (Planned)**  
  Will provide dashboards to visualize flakiness, historical failure trends, and team accountability metrics.

---

## 🛠️ How It Works

### Phase 1: Triage & Retry (MVP)

1. **Log Ingestion**  
   JARVIS parses Jenkins log files to extract details for all executed tests, focusing on failures.
   
2. **AI Classification**  
   Each failed test’s logs and stack trace are sent to an LLM, which classifies the root cause (e.g., Network Error, Assertion Failure, Test Data Issue) and flags failures as intermittent/retryable or permanent.
   
3. **Automated Retry**  
   Only retryable tests are re-run, reducing unnecessary pipeline executions.
   
4. **Final Reporting**  
   JARVIS generates an updated summary, showing which tests passed after retry and highlighting actionable failure categories.

---

## 📈 Roadmap

- **Phase 1:** Triage & Retry (MVP) – Completed
- **Phase 2:** Analytics & Visualization – Historical trend analysis, dashboards for flakiness and retry effectiveness - Work in Progress
- **Phase 3:** Self-Healing & Autonomous Remediation – Auto-suggest and generate PRs for basic code/config fixes - Planned

---

## 📦 Installation

> **Prerequisites:**  
> - Python 3.8+  
> - Test Results
> - OpenAI API Key   
> - Maven (for test rerun)
