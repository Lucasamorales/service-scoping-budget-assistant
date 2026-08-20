## **2\. The Execution Flow (Step-by-Step Logic)**

When the RAG identifies that a user is requesting a service with `Status: On demand`, the backend code must execute the following sequence:

### **Step 1: Tier & Price Lookup**

* **Action:** The system queries `the CSV`  to find the `Tier` assigned to the requested item.  
* **Action:** The system then queries `the CSV` to fetch the numeric `Price` for that specific Tier.

### **Step 2: Handle "Variable" Exception**

If the `Tier` returns as `Variable` (e.g., for Site Visits or Travel Attendance):

* **Action:** Abort automatic quoting.  
* **LLM Output Prompt:** *"This service involves third-party costs or travel expenses and requires a manual custom quote. Would you like me to send this request to your Account Manager so they can price it for you?"*  
* **Routing:** If the user says Yes, compile the chat and route the email to the **Account Manager**.

### **Step 3: Budget Calculation (For Standard Tiers 1, 2, 3\)**

If a numeric price is successfully retrieved:

* **Action:** Query `the CSV` to find the total monthly budget for the user's specific Branch.  
* **Action:** Query `the CSV` to sum all `Amount` spent by that Branch in the current month.  
* **Action:** Calculate `Remaining Budget` \= (Monthly Cap \- Spent Amount).

### **Step 4: LLM Response & Financial Routing**

* **LLM Output Prompt:** The LLM must present the calculated price and the user's remaining budget.  
  * *Example:* *"We can definitely do this\! Because this is a custom request, the cost will be \[Price\]. You currently have \[Remaining Budget\] left in your budget for this month."*  
* **Call to Action (CTA):** *"Would you like me to send an email to your Country Manager to request a Purchase Order (PO) for this?"*  
* **Routing:** If the user says Yes, compile the chat, the quote amount, and the budget context, then route the email to the **Country Manager**.

## **3\. Strict Rules for the LLM System Prompt**

* **Rule 1:** The LLM must **never** estimate, guess, or hardcode prices based on its training data. It must only output the `Price` variable passed to it by the backend python/database query.  
* **Rule 2:** If the user's `Remaining Budget` is lower than the `Price` of the quote, the LLM should actively flag this and suggest they will need to request additional funds from their Country Manager.

