# UNDERGRADUATE RESEARCH ASSISTANT TESTING PROTOCOL
## Adaptive Preference Testing System v3.5.11

**Assigned To**: [Student Name]  
**Supervisor**: Professor [Name], Cognitive Science Department, UCSD  
**Date Assigned**: November 2025  
**Estimated Time**: 8-12 hours (thorough testing)  
**Purpose**: Verify this system is ready for IRB submission and actual research use

---

## 🎯 YOUR MISSION

You are testing a **novel adaptive preference testing system** that uses Bayesian inference to efficiently measure human preferences. This is NOT a superficial "click around and see if it breaks" task. You need to:

1. **Understand** what adaptive preference testing is and why it matters
2. **Deploy** the system locally (following exact steps)
3. **Test** every workflow systematically (with documentation)
4. **Evaluate** the Bayesian algorithm's behavior mathematically
5. **Document** all findings (bugs, UX issues, suggestions)
6. **Certify** whether this is ready for real research participants

**If you find this system is broken or poorly designed, you MUST say so.** We need brutal honesty, not politeness.

---

## 📚 PART 0: BACKGROUND READING (Required - 2 hours)

### Why This Matters Scientifically

Traditional preference studies ask subjects to rate items on Likert scales (1-7) or rank them exhaustively. This has problems:
- **Cognitive load**: Rating 50 items on 7-point scales is tedious
- **Scale inconsistency**: Your "5" might be my "6"
- **Inefficiency**: Need many ratings for reliable estimates

**Adaptive methods** instead show pairs and ask "which do you prefer?" The algorithm learns your preferences and adaptively selects the most informative pairs. This:
- Reduces trials needed (50 vs 200+)
- Uses natural comparisons (easier than ratings)
- Maximizes information gain per trial

### Required Reading

**Before touching any code, read these:**

1. **Bradley-Terry Model** (15 minutes)
   - Wikipedia: "Bradley–Terry model"
   - Focus on: How pairwise comparisons estimate item "strengths"
   - Key equation: P(i beats j) = exp(μᵢ) / (exp(μᵢ) + exp(μⱼ))

2. **Adaptive Testing Basics** (20 minutes)
   - Search Google Scholar: "adaptive testing item response theory"
   - Key concept: Each response updates your belief about the subject's preferences
   - Analogy: Like a smart doctor who asks follow-up questions based on your answers

3. **Information Gain in Bayesian Inference** (25 minutes)
   - Wikipedia: "Information gain in decision trees"
   - Key concept: Entropy reduction
   - The algorithm selects pairs where the answer tells us the MOST about preferences

4. **This System's Documentation** (1 hour)
   - Read: `V3.5.11_COMPLETE_FEATURE_INVENTORY.md` (in the ZIP)
   - Read: `DEPLOYMENT_GUIDE.md` (in the ZIP)
   - Read: `README.md` (in the ZIP)

### Self-Check Questions (Answer these before proceeding)

1. What's the difference between asking "Rate this room 1-7" vs "Which room do you prefer?"
2. Why would showing random pairs be inefficient?
3. How does the Bradley-Terry model convert pairwise comparisons into ratings?
4. What does "information gain" mean in plain English?
5. Why is adaptive testing better than exhaustive pairwise comparison (all possible pairs)?

**If you can't answer these, go back and read more. You need to understand the WHY.**

---

## 📦 PART 1: SYSTEM SETUP (2-3 hours)

### Step 1.1: Extract the ZIP

```bash
cd ~/Desktop  # Or wherever you work
unzip COMPLETE_v3.5.11_ALL_GUI_FIXED.zip
cd COMPLETE_v3.5.11_SYSTEM
ls -la
```

**Verify you see**:
- `backend/` folder (Python API)
- `database/` folder (SQL schema)
- `frontend/` folder (HTML interfaces)
- `tests/` folder (Test suite)
- `VERSION.txt` (should say v3.5.11)
- `DEPLOYMENT_GUIDE.md`

**Document**: Take a screenshot of your file listing.

---

### Step 1.2: Install PostgreSQL

**macOS** (if not installed):
```bash
brew install postgresql@15
brew services start postgresql@15
createdb adaptive_testing
```

**Linux**:
```bash
sudo apt-get install postgresql postgresql-contrib
sudo systemctl start postgresql
sudo -u postgres createdb adaptive_testing
```

**Windows**:
- Download PostgreSQL installer
- Create database named `adaptive_testing`

**Verify**:
```bash
psql adaptive_testing -c "SELECT version();"
```

**Document**: Screenshot of successful connection.

---

### Step 1.3: Initialize Database Schema

```bash
cd database
psql adaptive_testing < schema.sql
```

**Verify tables created**:
```bash
psql adaptive_testing -c "\dt"
```

**You should see 9 tables**:
- users
- experiments
- stimuli
- sessions
- algorithm_state
- choices
- audit_log
- provenance_log
- schema_version

**Document**: Screenshot showing all 9 tables.

**Critical Check**: If you get errors about "relation already exists", the schema file has been run before. Drop and recreate:
```bash
psql adaptive_testing -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
psql adaptive_testing < schema.sql
```

---

### Step 1.4: Create Admin User

```bash
psql adaptive_testing
```

```sql
INSERT INTO users (user_id, email, username, password_hash, role, created_at)
VALUES (
    gen_random_uuid(),
    'admin@ucsd.edu',
    'admin',
    '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5oDhCQWxYPW.S',  -- password: "research123"
    'admin',
    NOW()
);
```

**Document**: Screenshot of successful INSERT.

**Important**: The password hash above corresponds to "research123". You'll use this to log in.

---

### Step 1.5: Install Python Dependencies

```bash
cd ../backend
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r ../requirements.txt
```

**Verify installation**:
```bash
pip list | grep -E "flask|psycopg2|numpy|scipy"
```

**You should see**:
- Flask ~= 3.0
- psycopg2-binary ~= 2.9
- numpy ~= 1.24
- scipy ~= 1.11

**Document**: Screenshot of pip list output.

---

### Step 1.6: Configure Database Connection

Create `.env` file in `backend/` folder:

```bash
cat > .env << EOF
DATABASE_URL=postgresql://localhost/adaptive_testing
JWT_SECRET=CHANGE_THIS_IN_PRODUCTION_TO_RANDOM_STRING_12345
FLASK_ENV=development
EOF
```

**Security Note**: The JWT_SECRET above is fine for testing but MUST be changed for production.

**Document**: Screenshot showing .env file created.

---

### Step 1.7: Start the API Server

```bash
# Make sure you're in backend/ with venv activated
export FLASK_APP=api.py
flask run --port=5000 --debug
```

**Expected output**:
```
 * Serving Flask app 'api.py'
 * Debug mode: on
 * Running on http://127.0.0.1:5000
```

**Verify API is running**:

Open a new terminal and run:
```bash
curl http://localhost:5000/api/health
```

**Expected response**:
```json
{"status": "healthy", "version": "3.5.11"}
```

**Document**: Screenshot of Flask running + curl response.

**If Flask fails to start**: Check error messages. Common issues:
- Port 5000 already in use → Use different port
- Database connection failed → Verify DATABASE_URL
- Import errors → Verify pip install succeeded

---

### Step 1.8: Serve Frontend Files

Open a SECOND terminal:

```bash
cd frontend
python3 -m http.server 8000
```

**Expected output**:
```
Serving HTTP on :: port 8000 (http://[::]:8000/) ...
```

**Document**: Screenshot showing both servers running (Flask on 5000, HTTP on 8000).

---

### Step 1.9: Initial Smoke Test

Open browser to: `http://localhost:8000/admin_PATCHED.html`

**You should see**:
- Dark themed page
- Title: "Experiment Admin Dashboard"
- Button: "+ Create New Experiment"
- Empty experiments table (no experiments yet)

**Document**: Screenshot of admin dashboard.

**If page doesn't load**: Check browser console (F12) for errors. Common issues:
- CORS errors → Make sure Flask is running
- 404 errors → Check you're on correct port (8000)
- JavaScript errors → Document and report

---

## ✅ PART 1 CHECKLIST

Before proceeding, verify ALL of these:
- [ ] PostgreSQL running
- [ ] Database `adaptive_testing` created
- [ ] 9 tables exist in database
- [ ] Admin user created (email: admin@ucsd.edu, password: research123)
- [ ] Python dependencies installed
- [ ] .env file configured
- [ ] Flask API running on port 5000
- [ ] HTTP server running on port 8000
- [ ] Admin dashboard loads in browser
- [ ] All documented with screenshots

**If ANY checkbox is unchecked, DO NOT proceed. Fix issues first.**

---

## 🧪 PART 2: FUNCTIONAL TESTING (3-4 hours)

### Test 2.1: User Authentication

**Purpose**: Verify security system works

**Steps**:
1. Open: `http://localhost:8000/admin_PATCHED.html`
2. You should see experiments list (public page)
3. Click "+ Create New Experiment"
4. This redirects to experimenter dashboard
5. You'll need to log in (JWT token)

**Current Issue**: The authentication flow may not be fully wired in the HTML. Check browser console.

**Test login API directly**:
```bash
curl -X POST http://localhost:5000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@ucsd.edu","password":"research123"}'
```

**Expected response**:
```json
{
  "token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "user": {
    "user_id": "...",
    "email": "admin@ucsd.edu",
    "role": "admin"
  }
}
```

**Document**:
- Screenshot of successful login curl
- Note whether HTML login works or needs fixing

**Critical Evaluation**:
- Does the token expire correctly? (Check after 8 hours)
- Can you use the token to access protected endpoints?
- What happens if you use wrong password?

---

### Test 2.2: Create an Experiment

**Purpose**: Full workflow from creation to publication

**Scenario**: You're running a study on "Interior Design Preferences" comparing 10 room layouts.

#### Step 2.2.1: Open Experimenter Dashboard

URL: `http://localhost:8000/experimenter_dashboard_improved.html`

**Verify**:
- [ ] Beautiful purple-blue gradient background (NOT flat gray!)
- [ ] White card in center
- [ ] 5-step wizard interface
- [ ] "Step 1: Basic Information" visible

**Document**: Screenshot of initial page.

**Critical Design Evaluation**:
- Is the gradient visually appealing? (Rate 1-10)
- Is the text readable on the gradient?
- Are the step indicators clear?
- Is it obvious what to do first?

---

#### Step 2.2.2: Fill Basic Information

**Enter**:
- Experiment Name: "Interior Design Preference Study"
- Description: "Compare modern vs traditional room layouts to understand aesthetic preferences"
- Click "Next"

**Verify**:
- [ ] Name appears in header
- [ ] Moved to Step 2 (Parameters)
- [ ] Can click "Previous" to go back

**Document**: Screenshot of completed Step 1.

**Critical Evaluation**:
- Are validation errors clear if you leave fields blank?
- Is the "Next" button obviously clickable?
- Does "Previous" work correctly?

---

#### Step 2.2.3: Configure Parameters

**This is critical - read carefully.**

**Enter**:
- Number of Stimuli: `10`
- Maximum Trials: `50`
- Confidence Threshold: `0.15` (default is fine)

**Understanding these parameters**:
- **Number of Stimuli**: How many items subjects compare (10 room images)
- **Maximum Trials**: Maximum pairwise comparisons (50 is typical)
- **Confidence Threshold**: Algorithm stops early if uncertainty drops below this

**Verify**:
- [ ] Parameter Wizard is present (yellow/orange box)
- [ ] Clicking wizard asks questions
- [ ] Help icons (?) show explanations

**Test the Parameter Wizard**:
1. Click "Use Parameter Wizard"
2. Answer questions it asks
3. Verify it suggests reasonable values
4. Note: Does it explain WHY these values?

**Document**:
- Screenshot of parameters page
- Screenshot of wizard interaction
- Your evaluation: Is wizard helpful or confusing?

**Critical Evaluation**:
- Are these parameters explained adequately?
- Would a naive student understand what they mean?
- Is the wizard actually helpful or just noise?

---

#### Step 2.2.4: Write Instructions

**This appears to subjects before they start.**

**Enter realistic instructions**:
```
Welcome to the Interior Design Preference Study!

You will see pairs of room images. For each pair, click the room you find more aesthetically pleasing.

There are no right or wrong answers - we want YOUR honest preferences.

The study takes about 8-10 minutes. Please complete in one sitting.

Tips:
• Trust your gut feeling
• Don't overthink it
• Consider overall aesthetic appeal, not specific furniture

Thank you for participating!
```

**Verify**:
- [ ] Instructions editor has formatting options (bold, italic, lists)
- [ ] Preview shows formatted text
- [ ] Instructions are saved when clicking "Next"

**Document**: Screenshot of instructions editor.

**Critical Evaluation**:
- Is the editor intuitive?
- Can you format text easily?
- Does preview match what subjects will see?

---

#### Step 2.2.5: Upload Stimuli (CRITICAL TEST)

**This is where images are stored in SQL as BYTEA.**

**You need 10 test images. Two options:**

**Option A**: Use provided test images (if included)
```bash
ls test_stimuli/
# Should have 10 .jpg or .png files
```

**Option B**: Create 10 placeholder images
```bash
# On macOS/Linux with ImageMagick:
for i in {1..10}; do
  convert -size 800x600 xc:blue -pointsize 72 -fill white \
    -draw "text 300,300 'Room $i'" room_$i.jpg
done
```

**Upload Process**:

1. **Test drag-and-drop**:
   - Drag all 10 images onto the upload area
   - Verify thumbnails appear
   - Verify file names shown

2. **Test paste from clipboard**:
   - Copy an image (Cmd+C)
   - Click "Paste from Clipboard"
   - Verify image appears

3. **Test file selector**:
   - Click "Choose Files"
   - Select multiple images
   - Verify all appear

**Verify for EACH image**:
- [ ] Thumbnail preview visible
- [ ] File name correct
- [ ] File size shown
- [ ] Can remove image (X button)

**Document**:
- Screenshot of uploaded images
- Screenshot of thumbnail grid
- Note which upload method works best

**Critical Evaluation**:
- Is drag-and-drop reliable?
- Are thumbnails clear enough?
- Can you easily remove wrong images?
- Is there a file size limit? (Test with huge image)
- What image formats are accepted? (Test .gif, .webp, .bmp)

**IMPORTANT**: Check browser Network tab (F12 → Network):
- When you upload, you should see POST requests to `/api/experiments/{id}/stimuli`
- Verify status 200 (success)
- Verify response shows stimulus_id

---

#### Step 2.2.6: Review and Publish

**Verify review screen shows**:
- [ ] Experiment name
- [ ] Description
- [ ] Parameters (10 stimuli, 50 trials)
- [ ] Instructions (formatted)
- [ ] All 10 image thumbnails
- [ ] "Publish Experiment" button

**Click "Publish Experiment"**

**Verify**:
- [ ] Success modal appears (🎉)
- [ ] Subject URL is displayed
- [ ] "Copy URL" button works
- [ ] URL format: `subject_interface_complete_PATCHED.html?exp={uuid}`

**Document**:
- Screenshot of review page
- Screenshot of success modal
- Screenshot of subject URL

**Copy the subject URL** - you'll need it!

**Critical Evaluation**:
- Is the review step necessary or redundant?
- Is the success modal celebratory enough? (This is a big moment!)
- Is the URL easy to copy and share?

---

#### Step 2.2.7: Verify Database Storage

**Open PostgreSQL**:
```bash
psql adaptive_testing
```

**Check experiment was created**:
```sql
SELECT experiment_id, name, num_stimuli, max_trials, status, created_at
FROM experiments
ORDER BY created_at DESC
LIMIT 1;
```

**Expected**: Your "Interior Design Preference Study" with status = 'active'

**Check stimuli were uploaded**:
```sql
SELECT experiment_id, stimulus_id, stimulus_index, filename, 
       length(file_data) as size_bytes,
       mime_type
FROM stimuli
WHERE experiment_id = (SELECT experiment_id FROM experiments 
                       ORDER BY created_at DESC LIMIT 1)
ORDER BY stimulus_index;
```

**Expected**: 10 rows, one for each image

**Verify**:
- [ ] All 10 stimuli present
- [ ] stimulus_index goes 0 to 9
- [ ] file_data is NOT NULL (images stored)
- [ ] size_bytes > 0 for all
- [ ] mime_type is 'image/jpeg' or 'image/png'

**Document**: Screenshot of SQL query results.

**Critical Evaluation**:
- Are images actually stored in database? (Check size_bytes)
- Is BYTEA storage reasonable for 10 images? (Calculate total MB)
- What happens with 50 images? 100? (Scalability question)

---

### Test 2.3: Subject Participation (MOST IMPORTANT TEST)

**This is the core of the system. Test thoroughly.**

#### Step 2.3.1: Initial Load

**Open the subject URL** you copied earlier:
`http://localhost:8000/subject_interface_complete_PATCHED.html?exp={uuid}`

**Verify**:
- [ ] Beautiful purple-blue gradient background (NOT flat!)
- [ ] White card in center
- [ ] Loading animation appears briefly
- [ ] Then transitions to consent screen

**Check browser console** (F12):
- Should see: `POST /api/sessions` with status 200
- Response should include: `session_token`

**Document**: Screenshot of consent screen.

**Critical Evaluation**:
- Is the loading smooth or janky?
- Is the gradient visually appealing?
- Are there console errors?

---

#### Step 2.3.2: Consent Flow (IRB Critical)

**The consent modal should appear.**

**Verify consent content**:
- [ ] Modal is centered and readable
- [ ] Consent text is displayed (from GET /api/consent)
- [ ] "I Agree" button is prominent
- [ ] "I Do Not Agree" button exists
- [ ] Can scroll through long consent text

**Test consent rejection**:
1. Click "I Do Not Agree"
2. Verify: Study does not proceed
3. Verify: Thank you message appears

**Test consent acceptance**:
1. Refresh page
2. Click "I Agree"
3. Verify: POST /api/sessions/{token}/consent with status 200
4. Verify: Transitions to instructions screen

**Document**:
- Screenshot of consent modal
- Screenshot of both "Agree" and "Disagree" outcomes
- Console log showing consent POST request

**Critical Evaluation (IRB Compliance)**:
- Is consent IMPOSSIBLE to skip?
- Is "I Do Not Agree" just as prominent as "I Agree"? (No dark patterns!)
- Is the consent text clear about:
  - What they're consenting to?
  - How data will be used?
  - That they can withdraw?
- Would UCSD IRB approve this flow?

**If consent is skippable or unclear, this is a CRITICAL BUG.**

---

#### Step 2.3.3: Instructions Screen

**After consenting, you see instructions.**

**Verify**:
- [ ] Instructions you wrote earlier are displayed
- [ ] Formatting is preserved (bold, lists, etc.)
- [ ] "Begin Experiment" button is clear
- [ ] Experiment name shown in header

**Document**: Screenshot of instructions screen.

**Critical Evaluation**:
- Are instructions readable on gradient background?
- Is "Begin" button obvious?
- Can subjects scroll if instructions are long?

---

#### Step 2.3.4: Trial 1 (First Comparison)

**Click "Begin Experiment"**

**The first trial should appear.**

**Verify**:
- [ ] Two images displayed side-by-side
- [ ] Images are large and clear
- [ ] Progress indicator shows "Trial 1/50"
- [ ] Hovering highlights each image
- [ ] Clicking an image records choice

**Critical Check**: 
Watch the Network tab (F12) when page loads:
- **GET /api/sessions/{token}/next** should be called
- Response should include: `{"stimulus_a_id": "...", "stimulus_b_id": "..."}`
- These IDs should correspond to your uploaded images

**Test image clarity**:
- Can you see details in both images?
- Are they loading fast enough?
- Is one image ever blank? (Bug)

**Document**:
- Screenshot of first trial
- Screenshot of Network tab showing /next request
- Screenshot of /next response JSON

**Critical Evaluation**:
- Are images large enough to make informed choice?
- Is the layout comfortable (not cramped)?
- Is it obvious which image you're choosing when hovering?

---

#### Step 2.3.5: Record Choice and Next Trial

**Click on the left image (your preference)**

**Verify**:
- [ ] Choice is recorded instantly (no lag)
- [ ] Transition to Trial 2 is smooth
- [ ] Progress bar updates (1/50 → 2/50)
- [ ] New pair of images appears

**Check Network tab**:
- **POST /api/sessions/{token}/choice** with status 200
- Request body should include: `{"chosen_stimulus_id": "...", "response_time_ms": ...}`
- **GET /api/sessions/{token}/next** fetches next pair

**Document**:
- Screenshot of Network tab showing choice POST
- Screenshot of Trial 2

**Critical Evaluation**:
- Is the transition smooth or jarring?
- Is response time being tracked? (Check request body)
- Does the next pair load instantly?

---

#### Step 2.3.6: Test Adaptive Selection (CRITICAL MATH TEST)

**This verifies the Bayesian algorithm is working.**

**Complete 10 trials**, choosing strategically:

**Trials 1-5**: Always choose stimulus #3 (if it appears)  
**Trials 6-10**: Always choose stimulus #7 (if it appears)

**Monitor which pairs are shown**:
- Write down each pair: (stimulusA, stimulusB, chosen)
- Example: (3, 5, 3), (7, 2, 7), (3, 7, 3), etc.

**After 10 trials, check database**:
```bash
psql adaptive_testing
```

```sql
-- Get your session
SELECT session_id, experiment_id, status, 
       (bayesian_state->>'mean_vector')::text as mean_vec
FROM sessions
WHERE status = 'in_progress'
ORDER BY created_at DESC
LIMIT 1;
```

**Expected**: The `mean_vector` should show higher values for stimuli you chose more (3 and 7).

**Deeper check**:
```sql
-- Get all choices in this session
SELECT trial_number, stimulus_a_id, stimulus_b_id, chosen_stimulus_id, response_time_ms
FROM choices
WHERE session_id = '{your-session-id}'
ORDER BY trial_number;
```

**Mathematical Verification**:
1. Are you seeing pairs with stimuli #3 and #7 more frequently? (Adaptive behavior)
2. Is the algorithm showing less of stimuli you never chose?
3. After 10 trials choosing #3 and #7, do later trials focus on comparing them against each other?

**Document**:
- Table of all 10 trials (pair shown, chosen)
- SQL output showing mean_vector
- Your interpretation: Is algorithm adapting?

**Critical Evaluation** (This is the heart of the system):
- **Is the algorithm truly adaptive?** 
  - If you keep choosing #3, does it stop showing obviously worse options?
  - Does it start showing #3 vs other strong candidates?
- **Is information gain maximization working?**
  - Are early trials exploratory (random pairs)?
  - Are later trials focused (comparing top items)?
- **Red flags**:
  - Same pair shown twice in a row (bug)
  - Pairs that make no sense given past choices (algorithm broken)
  - Convergence doesn't happen (stuck showing random pairs)

**If you suspect the algorithm ISN'T adapting, document this clearly. This is the system's most important feature.**

---

#### Step 2.3.7: Test Break Screens

**Continue until Trial 10/50**

**Verify**:
- [ ] After Trial 10, a "Take a Break" screen appears
- [ ] Break message is clear
- [ ] "Continue" button is present
- [ ] Progress shows 10/50 complete

**Test break behavior**:
- Is the break screen optional or mandatory?
- Can you skip it?
- Does it appear at other intervals (20, 30, 40)?

**Document**: Screenshot of break screen.

**Critical Evaluation**:
- Is break frequency appropriate? (Every 10 seems reasonable)
- Is the break message encouraging or annoying?
- Should breaks be customizable per experiment?

---

#### Step 2.3.8: Test Attention Checks (If Implemented)

**Some trials may include attention checks.**

**Look for**:
- Trials with instructions like "Please select the left image"
- Trials with obviously identical images
- Trials with one image much brighter/darker

**If an attention check appears**:
1. **Pass it correctly** (follow instruction)
2. **Fail it deliberately** (choose wrong)
3. Check what happens:
   - Is failure logged?
   - Does experiment continue?
   - Is failure counted against data quality?

**Check database**:
```sql
SELECT trial_number, is_attention_check, attention_check_passed
FROM choices
WHERE session_id = '{your-session-id}'
  AND is_attention_check = true;
```

**Document**:
- Screenshot of attention check trial
- SQL showing attention check results

**Critical Evaluation**:
- Are attention checks subtle enough?
- Would a real subject notice they're being tested?
- What happens if subject fails multiple checks?

---

#### Step 2.3.9: Complete Full Session

**Continue through all 50 trials** (yes, all 50!)

**While completing, note**:
- Average response time (are you getting faster?)
- Any duplicate pairs (BUG if this happens)
- Any trials where images don't load
- Any trials that feel "pointless" (bad pair selection)
- Fatigue level at trial 30, 40, 50

**After Trial 50**:
- [ ] Completion screen appears
- [ ] "Thank you" message displayed
- [ ] Debrief shown (if uploaded)
- [ ] Option to download completion certificate?
- [ ] Option to view your results?

**Check database**:
```sql
-- Session should be marked complete
SELECT session_id, status, completed_at, 
       (bayesian_state->>'mean_vector')::text as final_ratings
FROM sessions
WHERE session_id = '{your-session-id}';
```

**Expected**: 
- status = 'completed'
- completed_at IS NOT NULL
- final_ratings shows converged values

**Verify all 50 choices recorded**:
```sql
SELECT COUNT(*) FROM choices WHERE session_id = '{your-session-id}';
```

**Expected**: Exactly 50 rows

**Document**:
- Screenshot of completion screen
- Screenshot of debrief (if shown)
- SQL output showing session completion
- SQL output showing all 50 choices

**Time tracking**:
- How long did 50 trials take? (minutes:seconds)
- Was this reasonable for a subject?
- Were any trials frustratingly slow?

---

#### Step 2.3.10: Verify Bayesian Convergence

**This is the mathematical proof the system works.**

**Export your session data**:
```sql
\copy (SELECT trial_number, stimulus_a_id, stimulus_b_id, chosen_stimulus_id FROM choices WHERE session_id = '{your-session-id}' ORDER BY trial_number) TO '/tmp/my_session.csv' CSV HEADER;
```

**Analyze convergence**:

```python
# Run this Python script
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd

# Load your session data
df = pd.read_csv('/tmp/my_session.csv')

# Extract final ratings from database
# (You'll need to query bayesian_state->>'mean_vector')
final_ratings = [0.8, 1.2, 1.5, 0.3, -0.5, -0.8, 1.0, 0.9, -0.2, 0.1]  # Example
# Replace with YOUR actual final ratings from database

# Plot ratings
plt.figure(figsize=(10, 6))
plt.bar(range(len(final_ratings)), final_ratings)
plt.xlabel('Stimulus Index')
plt.ylabel('Bradley-Terry Rating (μ)')
plt.title('Final Preference Ratings After 50 Trials')
plt.axhline(y=0, color='r', linestyle='--', label='Neutral')
plt.legend()
plt.savefig('/tmp/final_ratings.png', dpi=150)
print("Ratings:", final_ratings)
print("Top 3 stimuli:", np.argsort(final_ratings)[-3:][::-1])
```

**Verify convergence**:
1. Do the highest-rated stimuli match what you actually preferred?
2. Are the lowest-rated stimuli ones you consistently rejected?
3. Is there a clear spread (not all ratings near zero)?

**Document**:
- Plot of final ratings
- List of top 3 stimuli by rating
- Your honest assessment: Do these ratings reflect your choices?

**Critical Evaluation**:
- **Does the math work?** Do ratings match your behavior?
- **Did it converge?** Or are ratings still uncertain after 50 trials?
- **Outliers?** Any stimuli with ratings that don't make sense?

**If ratings DON'T match your choices, the algorithm is BROKEN. This is a critical failure.**

---

### Test 2.4: Results Dashboard

**Purpose**: Verify researchers can view aggregated results

**Open**: `http://localhost:8000/results_dashboard_PATCHED.html?exp={experiment-id}`

**Verify**:
- [ ] Experiment name shown
- [ ] Summary statistics displayed:
  - Total sessions
  - Completed sessions
  - Average duration
  - Completion rate
- [ ] List of individual sessions
- [ ] CSV export button

**Test CSV Export**:
1. Click "Download CSV"
2. Verify file downloads
3. Open CSV in Excel/Numbers

**Expected CSV columns**:
- session_id
- trial_number
- stimulus_a_id
- stimulus_b_id
- chosen_stimulus_id
- response_time_ms
- timestamp

**Document**:
- Screenshot of results dashboard
- Screenshot of CSV in Excel
- Sample of CSV data (first 10 rows)

**Critical Evaluation**:
- Is the dashboard informative at a glance?
- Is the CSV format suitable for R/Python analysis?
- What's missing that a researcher would want?

---

### Test 2.5: Admin Dashboard

**Open**: `http://localhost:8000/admin_PATCHED.html`

**Verify**:
- [ ] Beautiful dark theme (not broken light borders!)
- [ ] List of all experiments
- [ ] Each experiment shows:
  - Name
  - Status (active/draft)
  - Date created
  - Number of sessions
  - Actions (View Results button)

**Test Consent/Debrief Upload**:
1. Scroll to "Consent & Debrief" section
2. Upload a test HTML file as consent
3. Click "Preview consent" link
4. Verify your uploaded file is shown

**Document**:
- Screenshot of admin dashboard (verify dark theme is consistent)
- Screenshot of uploaded consent preview

**Critical Evaluation**:
- Is the dark theme professional?
- Are all experiments easily visible?
- Is the consent upload feature intuitive?

---

## ✅ PART 2 CHECKLIST

Complete testing requires ALL of these:
- [ ] Created experiment via dashboard
- [ ] Uploaded 10 images (stored in SQL as BYTEA)
- [ ] Published experiment
- [ ] Verified database storage (experiments, stimuli tables)
- [ ] Completed full 50-trial subject session
- [ ] Verified consent flow (cannot skip)
- [ ] Tested instructions screen
- [ ] Recorded all 50 choices in database
- [ ] Verified Bayesian adaptive selection (algorithm adapts to choices)
- [ ] Checked mathematical convergence (ratings match behavior)
- [ ] Tested break screens
- [ ] Tested attention checks (if implemented)
- [ ] Viewed results dashboard
- [ ] Exported CSV data
- [ ] Tested admin dashboard
- [ ] All documented with screenshots and SQL queries

**If ANY checkbox is unchecked, testing is incomplete.**

---

## 🔬 PART 3: ALGORITHMIC VALIDATION (2-3 hours)

**This section requires Python/math background. If you're not comfortable with code, skip to Part 4.**

### Test 3.1: Verify Sherman-Morrison Update

**Purpose**: Ensure covariance updates are mathematically correct

**Run this test**:
```python
import numpy as np
import sys
sys.path.append('backend/')
from bayesian_adaptive import PureBayesianAdaptiveSelector

# Initialize with 5 stimuli
selector = PureBayesianAdaptiveSelector(n_stimuli=5)

# Initial covariance should be identity matrix
print("Initial Σ:")
print(selector.covariance)
assert np.allclose(selector.covariance, np.eye(5)), "Initial covariance not I"

# Simulate: stimulus 0 beats stimulus 1
selector.update(winner_idx=0, loser_idx=1)

# Verify covariance changed
print("\nAfter update Σ:")
print(selector.covariance)
assert not np.allclose(selector.covariance, np.eye(5)), "Covariance didn't change"

# Verify it's still positive definite
eigenvalues = np.linalg.eigvals(selector.covariance)
print("\nEigenvalues:", eigenvalues)
assert np.all(eigenvalues > 0), "Covariance not positive definite"

# Verify Sherman-Morrison rank-1 property
# Σ_new = Σ_old - (Σu)(uᵀΣ)/(1 + uᵀΣu)
# This update should have rank 1 difference
diff = selector.covariance - np.eye(5)
rank = np.linalg.matrix_rank(diff, tol=1e-10)
print("\nRank of Σ - I:", rank)
assert rank <= 2, "Update has rank > 2 (should be rank-1 or rank-2 for 2-participant update)"

print("\n✅ Sherman-Morrison update is correct")
```

**Document**:
- Output of this test
- Did assertions pass?
- Are eigenvalues all positive?

**Critical Evaluation**:
- Is the math implementation correct?
- Does covariance stay positive definite?
- Is Sherman-Morrison more efficient than full matrix inversion?

---

### Test 3.2: Verify Information Gain Calculation

**Purpose**: Ensure algorithm selects maximally informative pairs

**Test**:
```python
import numpy as np
from bayesian_adaptive import PureBayesianAdaptiveSelector

# Start fresh
selector = PureBayesianAdaptiveSelector(n_stimuli=5)

# Manually set some preferences (e.g., we know 0 > 1 > 2)
selector.mean_vector = np.array([1.0, 0.5, 0.0, -0.5, -1.0])
# High uncertainty between 1 and 2
selector.covariance = np.eye(5) * 0.8
selector.covariance[1, 1] = 2.0
selector.covariance[2, 2] = 2.0

# Get next pair
pair, info_gain = selector.select_pair()
print(f"Selected pair: {pair}")
print(f"Information gain: {info_gain}")

# Expected: Should select pair (1, 2) because they're close in rating
# and have high uncertainty
assert pair == (1, 2) or pair == (2, 1), f"Didn't select maximally uncertain pair: {pair}"

print("✅ Information gain maximization is correct")
```

**Document**:
- Which pair was selected?
- Was it the expected pair (1,2)?
- What was the information gain value?

**Critical Evaluation**:
- Does the selector prefer uncertain comparisons?
- Would it get stuck showing the same pairs?
- Is there exploration-exploitation balance?

---

### Test 3.3: Convergence Speed Test

**Purpose**: How many trials until ratings stabilize?

**Simulation**:
```python
import numpy as np
from bayesian_adaptive import PureBayesianAdaptiveSelector

# Ground truth ratings
true_ratings = np.array([1.5, 0.8, 0.3, -0.2, -0.9, -1.5])
n = len(true_ratings)

# Initialize selector
selector = PureBayesianAdaptiveSelector(n_stimuli=n)

# Simulate subject who chooses according to Bradley-Terry model
def simulate_choice(i, j, true_ratings, noise=0.1):
    """Subject chooses i over j with probability σ(μᵢ - μⱼ + noise)"""
    diff = true_ratings[i] - true_ratings[j] + np.random.normal(0, noise)
    return i if diff > 0 else j

# Run 100 trials
estimates = []
uncertainties = []
for trial in range(100):
    # Get next pair
    i, j = selector.select_pair()
    
    # Simulate choice
    winner = simulate_choice(i, j, true_ratings)
    loser = j if winner == i else i
    
    # Update
    selector.update(winner, loser)
    
    # Track estimates
    estimates.append(selector.mean_vector.copy())
    uncertainties.append(np.diag(selector.covariance).mean())

# Check convergence
import matplotlib.pyplot as plt
from scipy.stats import spearmanr

# Plot convergence
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))

# Plot rating evolution
estimates = np.array(estimates)
for i in range(n):
    ax1.plot(estimates[:, i], label=f'Stimulus {i}')
    ax1.axhline(true_ratings[i], linestyle='--', color='gray', alpha=0.5)
ax1.set_xlabel('Trial')
ax1.set_ylabel('Estimated Rating')
ax1.set_title('Rating Convergence')
ax1.legend()
ax1.grid(True, alpha=0.3)

# Plot uncertainty
ax2.plot(uncertainties)
ax2.set_xlabel('Trial')
ax2.set_ylabel('Average Uncertainty')
ax2.set_title('Uncertainty Reduction')
ax2.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig('/tmp/convergence_test.png', dpi=150)

# Calculate Spearman correlation at different points
correlations = []
for trial in range(10, 100, 10):
    corr, _ = spearmanr(estimates[trial], true_ratings)
    correlations.append((trial, corr))
    print(f"Trial {trial}: Spearman ρ = {corr:.3f}")

# Final correlation
final_corr, _ = spearmanr(estimates[-1], true_ratings)
print(f"\nFinal correlation: {final_corr:.3f}")
assert final_corr > 0.9, f"Poor convergence: ρ = {final_corr}"

print("✅ Convergence test passed")
```

**Document**:
- Convergence plot (/tmp/convergence_test.png)
- Spearman correlations at trials 10, 20, 30, ..., 100
- Final correlation (should be > 0.9)

**Critical Evaluation**:
- How many trials until ρ > 0.8? (Good convergence)
- Does uncertainty decrease monotonically?
- Are 50 trials sufficient for 10 stimuli?

---

### Test 3.4: Attention Check Detection

**Purpose**: Verify quality control mechanisms

**If attention checks are implemented, test**:
```sql
-- Get all sessions with failed attention checks
SELECT s.session_id, 
       COUNT(*) FILTER (WHERE c.is_attention_check = true) as total_checks,
       COUNT(*) FILTER (WHERE c.is_attention_check = true AND NOT c.attention_check_passed) as failed_checks,
       COUNT(*) FILTER (WHERE c.response_time_ms < 500) as fast_responses
FROM sessions s
JOIN choices c ON s.session_id = c.session_id
WHERE s.status = 'completed'
GROUP BY s.session_id
HAVING COUNT(*) FILTER (WHERE c.is_attention_check = true AND NOT c.attention_check_passed) > 0
   OR COUNT(*) FILTER (WHERE c.response_time_ms < 500) > 2;
```

**Document**:
- How many sessions flagged?
- What are the flagging criteria?
- Are they reasonable?

**Critical Evaluation**:
- Are attention checks effective?
- Are they too easy or too hard?
- Should failed sessions be excluded from analysis?

---

## ✅ PART 3 CHECKLIST

- [ ] Sherman-Morrison update verified mathematically
- [ ] Information gain maximization verified
- [ ] Convergence speed tested (ρ > 0.9 within 50-100 trials)
- [ ] Uncertainty decreases monotonically
- [ ] Attention check detection works (if implemented)
- [ ] All tests documented with plots and outputs

---

## 🐛 PART 4: BUG HUNTING & UX EVALUATION (2-3 hours)

**Your mission**: Find problems. Be ruthless.

### Test 4.1: Edge Cases & Error Handling

**Test these scenarios and document what happens:**

1. **No images uploaded**
   - Create experiment, skip image upload
   - Try to publish
   - Expected: Error message
   - Actual: ?

2. **Wrong image format**
   - Upload a .txt file renamed to .jpg
   - Expected: Validation error
   - Actual: ?

3. **Duplicate experiment names**
   - Create two experiments with same name
   - Expected: Allowed (or warning?)
   - Actual: ?

4. **Empty instructions**
   - Leave instructions blank
   - Try to publish
   - Expected: Validation error or default instructions
   - Actual: ?

5. **Incomplete session**
   - Start session, complete 10 trials, close browser
   - Reopen same URL
   - Expected: Resume from trial 11 (or restart?)
   - Actual: ?

6. **Invalid experiment ID**
   - Open subject_interface.html?exp=invalid-uuid
   - Expected: "Experiment not found" error
   - Actual: ?

7. **Expired JWT token**
   - Get login token
   - Wait 8+ hours
   - Try to use token
   - Expected: 401 Unauthorized, redirect to login
   - Actual: ?

8. **Concurrent sessions**
   - Open same experiment in two browser tabs
   - Complete trials in both
   - Expected: Two separate sessions (not conflict)
   - Actual: ?

9. **Database connection lost**
   - Stop PostgreSQL: `brew services stop postgresql` (macOS)
   - Try to load admin dashboard
   - Expected: Clear error message
   - Actual: ?
   - Restart PostgreSQL: `brew services start postgresql`

10. **Extremely large image**
    - Try uploading a 50MB image
    - Expected: File size limit error
    - Actual: ?

**For EACH scenario, document**:
- What happened
- Was error message clear?
- Did system crash or recover gracefully?
- Rate error handling 1-10

---

### Test 4.2: Browser Compatibility

**Test on multiple browsers**:
- Chrome (primary)
- Firefox
- Safari (if on Mac)
- Edge (if on Windows)

**For each browser, verify**:
- [ ] Experimenter dashboard loads
- [ ] Image upload works (drag-drop, paste)
- [ ] Subject interface loads
- [ ] Gradient backgrounds render correctly
- [ ] Modals appear correctly
- [ ] API calls succeed

**Document**:
- Which browsers fully work?
- Any browser-specific bugs?
- CSS rendering issues?

---

### Test 4.3: Mobile/Tablet Testing

**Open on mobile device** (or use browser dev tools mobile emulation):

**Experimenter Dashboard**:
- [ ] Is it usable on mobile?
- [ ] Can you upload images?
- [ ] Can you fill forms?

**Subject Interface**:
- [ ] Can you complete trials?
- [ ] Are images large enough?
- [ ] Is tapping accurate?

**Document**:
- Screenshots from mobile
- Is mobile support necessary?
- Rate mobile experience 1-10

---

### Test 4.4: Accessibility (A11Y) Testing

**Use screen reader** (if available):
- macOS: Enable VoiceOver (Cmd+F5)
- Windows: Enable Narrator

**Navigate subject interface with keyboard only**:
- Tab through all elements
- Space/Enter to select images
- Verify: Can complete entire session without mouse

**Check WCAG compliance**:
- Are there alt texts on images?
- Is color contrast sufficient?
- Are focus states visible?
- Are ARIA labels present?

**Document**:
- Can you navigate with keyboard?
- Rate accessibility 1-10
- What needs improvement?

---

### Test 4.5: Performance Testing

**Measure load times**:

1. **Experimenter dashboard with 100 images**
   - Upload 100 images (if possible)
   - Does upload succeed?
   - How long does it take?

2. **Subject interface trial loading**
   - Time from clicking image → next trial appears
   - Expected: < 500ms
   - Actual: ?

3. **Database query speed**
   ```sql
   EXPLAIN ANALYZE
   SELECT * FROM choices WHERE session_id = '{id}';
   ```
   - Execution time?
   - Are indexes used?

**Document**:
- Load times for each operation
- Bottlenecks identified
- Optimization suggestions

---

### Test 4.6: Security Testing

**Attempt basic attacks** (ethical testing only):

1. **SQL Injection**
   - Try to create experiment with name: `'; DROP TABLE experiments; --`
   - Expected: Safely escaped, no SQL executed
   - Actual: ?

2. **XSS (Cross-Site Scripting)**
   - Try to create experiment with name: `<script>alert('XSS')</script>`
   - View experiment list
   - Expected: Script not executed, displayed as text
   - Actual: ?

3. **CSRF (Cross-Site Request Forgery)**
   - Create experiment while logged in
   - Log out
   - Try to resubmit same POST request
   - Expected: Rejected (invalid/expired token)
   - Actual: ?

4. **Path Traversal**
   - Try to access: `http://localhost:5000/api/../../../../etc/passwd`
   - Expected: 404 or 403
   - Actual: ?

**Document**:
- Which attacks succeeded? (CRITICAL BUGS)
- Security rating 1-10

---

### Test 4.7: Data Integrity Testing

**Verify database constraints**:

1. **Try to insert invalid data**:
```sql
-- Duplicate session token (should fail)
INSERT INTO sessions (session_id, session_token, experiment_id, status)
VALUES (gen_random_uuid(), 'existing-token', 
        (SELECT experiment_id FROM experiments LIMIT 1), 'in_progress');
```

Expected: `ERROR: duplicate key value violates unique constraint`

2. **Foreign key constraints**:
```sql
-- Try to insert choice for non-existent session
INSERT INTO choices (choice_id, session_id, trial_number, stimulus_a_id, stimulus_b_id, chosen_stimulus_id)
VALUES (gen_random_uuid(), gen_random_uuid(), 1, 
        gen_random_uuid(), gen_random_uuid(), gen_random_uuid());
```

Expected: `ERROR: violates foreign key constraint`

3. **Check NOT NULL constraints**:
```sql
-- Try to create experiment without name
INSERT INTO experiments (experiment_id, num_stimuli, max_trials)
VALUES (gen_random_uuid(), 10, 50);
```

Expected: `ERROR: null value in column "name" violates not-null constraint`

**Document**:
- Do all constraints work?
- Can you corrupt the database?
- Rating: Data integrity 1-10

---

## ✅ PART 4 CHECKLIST

- [ ] Tested 10+ edge cases
- [ ] Tested 3+ browsers
- [ ] Tested mobile/tablet (or emulation)
- [ ] Tested keyboard-only navigation
- [ ] Measured performance (load times)
- [ ] Tested basic security (SQL injection, XSS)
- [ ] Verified database constraints
- [ ] All bugs documented with severity ratings

---

## 📊 PART 5: FINAL EVALUATION & REPORT (2 hours)

### Deliverable: Testing Report

Create a document (Google Doc or Markdown) with these sections:

---

### Section 1: Executive Summary

**System Name**: Adaptive Preference Testing System v3.5.11  
**Tested By**: [Your Name]  
**Testing Period**: [Start Date] - [End Date]  
**Total Testing Hours**: [X hours]  

**Overall Assessment**: [Ready for Production / Needs Minor Fixes / Needs Major Fixes / Not Ready]

**Key Findings**:
- [Bullet point: Major strength #1]
- [Bullet point: Major strength #2]
- [Bullet point: Critical bug #1]
- [Bullet point: Critical bug #2]

---

### Section 2: Test Coverage

| Test Area | Tests Executed | Pass Rate | Notes |
|-----------|---------------|-----------|-------|
| Setup & Deployment | 9/9 | 100% | |
| Experiment Creation | 12/12 | 100% | |
| Image Upload | 8/8 | 100% | |
| Subject Participation | 15/15 | 100% | |
| Bayesian Algorithm | 5/5 | 100% | |
| Data Export | 3/3 | 100% | |
| Edge Cases | 10/10 | 80% | 2 issues |
| Security | 4/4 | 75% | 1 vulnerability |
| **TOTAL** | **66/66** | **95%** | |

---

### Section 3: Critical Bugs

**List any bugs that would prevent research use:**

#### Bug #1: [Title]
- **Severity**: Critical / High / Medium / Low
- **Description**: [What's broken?]
- **Steps to Reproduce**:
  1. [Step 1]
  2. [Step 2]
- **Expected Behavior**: [What should happen?]
- **Actual Behavior**: [What happens instead?]
- **Impact**: [How does this affect research?]
- **Screenshots**: [Attach]

[Repeat for each bug]

---

### Section 4: UX Evaluation

**Rate each interface 1-10 (1=unusable, 10=excellent):**

| Interface | Rating | Strengths | Weaknesses |
|-----------|--------|-----------|------------|
| Experimenter Dashboard | 8/10 | Beautiful gradient, clear wizard | Image upload could be faster |
| Subject Interface | 9/10 | Simple, intuitive | Break screens too frequent |
| Admin Dashboard | 7/10 | Good dark theme | Table could be sortable |
| Results Dashboard | 6/10 | Basic functionality | Lacks visualizations |

**Overall UX Rating**: [X/10]

---

### Section 5: Algorithm Validation

**Bayesian Adaptive Selection**:
- ✅ / ❌ Algorithm adapts to user choices
- ✅ / ❌ Information gain maximization works
- ✅ / ❌ Convergence achieved within 50 trials
- ✅ / ❌ Final ratings match observed behavior

**Spearman Correlation**: ρ = [X.XX] (target: > 0.9)

**Mathematical Correctness**:
- ✅ / ❌ Sherman-Morrison update correct
- ✅ / ❌ Covariance stays positive definite
- ✅ / ❌ Bradley-Terry likelihood correct

**Algorithm Rating**: [X/10]

---

### Section 6: IRB Readiness

**Ethical Considerations**:
- ✅ / ❌ Consent cannot be skipped
- ✅ / ❌ Consent text is clear
- ✅ / ❌ "I Do Not Agree" option prominent
- ✅ / ❌ Data collection transparent
- ✅ / ❌ Withdrawal procedure clear
- ✅ / ❌ Debrief provided after completion

**IRB Readiness**: [Ready / Needs Changes]

**Recommendations for IRB submission**:
- [Recommendation #1]
- [Recommendation #2]

---

### Section 7: Performance & Scalability

**Load Times**:
- Experimenter dashboard initial load: [X]ms
- Image upload (10 images): [X]s
- Subject interface initial load: [X]ms
- Trial transition time: [X]ms

**Database Performance**:
- Query response time: [X]ms (avg)
- Total database size after 50-trial session: [X]MB

**Scalability Concerns**:
- [Concern #1: e.g., "BYTEA storage inefficient for 100+ images"]
- [Concern #2]

---

### Section 8: Recommendations

**Must Fix Before Production**:
1. [Critical issue #1]
2. [Critical issue #2]

**Should Fix (High Priority)**:
1. [High priority issue #1]
2. [High priority issue #2]

**Nice to Have (Enhancements)**:
1. [Enhancement #1]
2. [Enhancement #2]

---

### Section 9: Comparison to Alternatives

**How does this compare to**:
- **Pavlovia**: [Better/Worse/Equal] because [reason]
- **PsychoPy**: [Better/Worse/Equal] because [reason]
- **Qualtrics**: [Better/Worse/Equal] because [reason]

**Unique Advantages**:
- [Advantage #1]
- [Advantage #2]

**Disadvantages**:
- [Disadvantage #1]
- [Disadvantage #2]

---

### Section 10: Final Recommendation

**Is this system ready for use in your research?**

[Write 2-3 paragraphs with your honest assessment]

**Certification**: 

☐ I certify this system is ready for IRB submission and research use  
☐ I certify this system needs minor fixes before research use  
☐ I cannot certify this system for research use due to critical issues

**Signed**: [Your Name]  
**Date**: [Date]

---

## 📧 DELIVERABLES TO PROFESSOR

Submit via email:

1. **Testing Report** (Google Doc or PDF)
2. **Screenshots Folder** (ZIP with all screenshots)
3. **Database Dumps**:
   ```bash
   pg_dump adaptive_testing > adaptive_testing_backup.sql
   ```
4. **Session Data**: Your completed 50-trial session CSV
5. **Convergence Plots**: Rating evolution, uncertainty reduction
6. **Bug Report**: Separate document if critical bugs found

---

## ⏰ ESTIMATED TIME BREAKDOWN

| Part | Task | Time |
|------|------|------|
| 0 | Background Reading | 2h |
| 1 | System Setup | 2-3h |
| 2 | Functional Testing | 3-4h |
| 3 | Algorithm Validation | 2-3h |
| 4 | Bug Hunting | 2-3h |
| 5 | Report Writing | 2h |
| **TOTAL** | | **13-17h** |

**Spread over**: 2-3 days recommended (don't rush)

---

## 🎓 LEARNING OUTCOMES

By completing this testing protocol, you will:

1. **Understand adaptive testing**: How Bayesian methods improve efficiency
2. **Experience full-stack testing**: Frontend, backend, database, algorithm
3. **Practice scientific rigor**: Not just "does it work?" but "does it work *correctly*?"
4. **Develop critical thinking**: Find bugs, evaluate UX, assess readiness
5. **Gain research skills**: Verify mathematical correctness, convergence analysis

**This is NOT busywork.** If this system has bugs, your testing will find them. If it's ready for real research, your certification matters.

---

## ❓ QUESTIONS FOR PROFESSOR

If you need help:
- **Setup issues**: Email logs and error messages
- **Conceptual questions**: Schedule office hours
- **Bug uncertainties**: Document and ask "Is this a bug or expected?"
- **Math questions**: Ask about Bayesian inference, Bradley-Terry model

**Do NOT**:
- Say "it works fine" without thorough testing
- Gloss over bugs to avoid reporting bad news
- Skip the math validation (that's the core!)

---

## 📚 ADDITIONAL RESOURCES FOR STUDENTS

If other students need to understand adaptive preference testing before using this system, here's what they should read:

### Recommended Preparatory Materials

**For Experimenters (Researchers Creating Studies)**:

1. **Tutorial Document Needed**: "Introduction to Adaptive Preference Testing"
   - What is pairwise comparison?
   - Why adaptive instead of exhaustive?
   - When to use this vs Likert scales?
   - How to interpret results?

2. **Practical Guide Needed**: "Creating Your First Experiment"
   - Step-by-step with screenshots
   - Common mistakes to avoid
   - Best practices for instruction writing
   - Image selection guidelines

**For Subjects (Research Participants)**:

1. **Participant Information Sheet Needed**:
   - What is this study about?
   - How long will it take?
   - What will I be doing?
   - How is my data used?

**Prompt for Creating These Materials**:

```
I need educational materials for a Bayesian adaptive preference testing system. Please create:

1. A 2-page "Experimenter's Quick Start Guide" explaining:
   - What adaptive testing is (vs traditional methods)
   - When to use pairwise comparisons vs ratings
   - How the Bayesian algorithm works (conceptually, not mathematically)
   - Best practices for stimulus selection
   - How to interpret Bradley-Terry ratings
   Target audience: Graduate students in psychology/cognitive science

2. A 1-page "Participant Information Sheet" explaining:
   - What happens during a session
   - Why they see certain image pairs
   - How long it takes
   - What data is collected
   Target audience: Undergraduate research participants (lay audience)

3. A 3-page "Technical Deep Dive" explaining:
   - Bradley-Terry model mathematics
   - Bayesian inference for pairwise comparisons
   - Information gain maximization
   - Sherman-Morrison covariance updates
   Target audience: Advanced students with linear algebra background

Please make these concrete, practical, and example-driven.
```

---

## 🎯 FINAL NOTES FOR TESTING

**Remember**:
- **Be thorough**, not superficial
- **Document everything** with screenshots
- **Test the math**, not just the UI
- **Find bugs**, don't hide them
- **Assess honestly**, not politely

**The goal is NOT to "pass" the system. The goal is to VERIFY it.**

If this system is broken, we need to know NOW, not after IRB submission or worse, after collecting bad data.

**Your testing matters. Take it seriously.**

---

**Good luck! 🚀**
