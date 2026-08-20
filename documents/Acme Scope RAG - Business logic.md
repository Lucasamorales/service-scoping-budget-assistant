#### **🟢 Flow 1: The "In-Scope" Route**

*Triggered when RAG reads: Status: Yes (e.g., Campaign wrap-ups)*

* **Step 1: Classification & Response**  
  * The LLM informs the user: *"Yes, we can do this and it is included in our scope (Free of Charge)."*  
* **Step 2: Budget Context (Optional but helpful)**  
  * The system checks Acme\_Scope\_RAG\_DB\_Budget\_caps.csv for the user's Branch and current month.  
  * The system checks Acme\_Scope\_RAG\_DB\_DB.csv to sum up the current month's spending.  
  * The LLM casually reminds them of their remaining monthly budget just for awareness.  
* **Step 3: Call to Action (CTA)**  
  * The LLM prompts: *"Would you like me to ping your Account Manager with this request?"*  
* **Step 4: Execution**  
  * If the user says Yes $\\rightarrow$ The tool captures the chat context, drafts an email, and sends it to the AM.

#### **🟡 Flow 2: The "Ad-Hoc / Quote Required" Route**

*Triggered when RAG reads: Status: On demand*

* **Step 1: Classification & Response**  
  * The LLM informs the user: *"This service is available 'On demand', which means it requires a custom quote."*  
* **Step 2: Quoting & Budget Calculation**  
  * **Action A:** The system triggers the Quoting Add-on to calculate the estimated cost based on the user's parameters.  
  * **Action B:** The system checks Acme\_Scope\_RAG\_DB\_Budget\_caps.csv (e.g., Acme Calgary has a 400 cap).  
  * **Action C:** The system checks Acme\_Scope\_RAG\_DB\_DB.csv for previous expenses to calculate the exact Remaining Budget.  
* **Step 3: Financial Presentation & CTA**  
  * The LLM presents the Quote alongside the Remaining Budget.  
  * *Logic Check:* If Quote \> Remaining Budget, the LLM flags that they will need to request additional funds.  
  * The LLM prompts: *"Would you like to send an email to your Country Manager to request a Purchase Order (PO) for this?"*  
* **Step 4: Execution**  
  * If the user says Yes $\\rightarrow$ The tool compiles the quote, budget context, and chat history, then drafts/sends the email to the Country Manager.

#### **🔴 Flow 3: The "Out-of-Scope" Route**

*Triggered when RAG reads: Status: Local OR Status: No*

* **Step 1: Classification & Response**  
  * If Local: The LLM informs the user: *"This task is handled internally by your local team, not central marketing."*

  * If No: The LLM informs the user: *"This falls completely outside of our service scope."*

* **Step 2: Value-Add**  
  * The LLM pulls any "Likely Questions" or "Summary" advice from the retrieved Markdown document to guide the user on how they can handle it themselves.  
* **Step 3: Execution**  
  * Flow terminates. No quoting tool is triggered, and no emails are drafted.

