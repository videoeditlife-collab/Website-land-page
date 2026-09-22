/**
 * Gmail outreach sequencer — Google Apps Script.
 *
 * Runs a three-touch sequence from a Google Sheet: initial email, follow-up
 * after 3 days, follow-up after 4 days, stopping the moment someone replies.
 *
 * Sends as whatever Google account it is installed under. To send from
 * jbobbycreative@gmail.com, sign into THAT account before creating the Sheet
 * and the script — nothing else is needed, and no alias setup is involved.
 *
 * SETUP
 *  1. Sign into jbobbycreative@gmail.com.
 *  2. sheets.new, then File > Import > Upload outreach_drafts.csv.
 *     Rename the tab to "Outreach".
 *  3. Columns used (headers must match exactly; extras are ignored):
 *       Email | FirstName | Channel | Subject | Body
 *       Followup1 | Followup2 | Status | ThreadId | LastSent | Touch
 *     Body/Followup1/Followup2 hold YOUR copy. Placeholders {{firstName}},
 *     {{channel}}, {{subs}}, {{cadence}} are filled from the row.
 *  4. Extensions > Apps Script, paste this file, Save.
 *  5. Run `run` once by hand and grant permissions.
 *  6. Triggers > Add Trigger > run > Time-driven > Day timer > 9am-10am.
 *
 * Leave DRY_RUN true for the first pass. It writes what it would send to the
 * log and to the Status column without sending anything.
 */

const SHEET_NAME = 'Outreach';
const DAILY_CAP = 12;
const FOLLOWUP_1_AFTER_DAYS = 3;
const FOLLOWUP_2_AFTER_DAYS = 4;
const DRY_RUN = true;

// A row is skipped unless every one of these is filled in. The hook is the
// line that decides whether the mail is read, and a merge that sends with an
// empty one burns the address for nothing.
const REQUIRED = ['Email', 'Subject', 'Body'];

// Copy still carrying the placeholder from the generated CSV is not finished.
const UNFILLED = /\[WATCH\]|\{\{\s*\w+\s*\}\}/;


function run() {
  const sheet = SpreadsheetApp.getActive().getSheetByName(SHEET_NAME);
  if (!sheet) throw new Error('No sheet named ' + SHEET_NAME);

  const data = sheet.getDataRange().getValues();
  const col = {};
  data[0].forEach((name, i) => col[String(name).trim()] = i);

  ['Email', 'Subject', 'Body', 'Status', 'ThreadId', 'LastSent', 'Touch']
    .forEach(name => {
      if (col[name] === undefined) throw new Error('Missing column: ' + name);
    });

  let sent = 0;

  for (let r = 1; r < data.length && sent < DAILY_CAP; r++) {
    const row = data[r];
    const status = String(row[col.Status] || '').trim();
    if (status === 'done' || status === 'replied' || status === 'skip') continue;

    const missing = REQUIRED.filter(name =>
      col[name] === undefined || !String(row[col[name]] || '').trim());
    if (missing.length) {
      setCell(sheet, r, col.Status, 'needs ' + missing.join(', '));
      continue;
    }

    const touch = Number(row[col.Touch] || 0);
    const threadId = String(row[col.ThreadId] || '').trim();

    if (threadId && hasReply(threadId)) {
      setCell(sheet, r, col.Status, 'replied');
      continue;
    }

    if (touch > 0) {
      const needed = touch === 1 ? FOLLOWUP_1_AFTER_DAYS : FOLLOWUP_2_AFTER_DAYS;
      if (daysSince(row[col.LastSent]) < needed) continue;
    }

    const bodyColumn = touch === 0 ? 'Body'
                     : touch === 1 ? 'Followup1' : 'Followup2';
    if (col[bodyColumn] === undefined) {
      setCell(sheet, r, col.Status, 'done');
      continue;
    }

    const rawBody = String(row[col[bodyColumn]] || '').trim();
    if (!rawBody) {
      // No follow-up written for this stage: stop here rather than resend.
      setCell(sheet, r, col.Status, 'done');
      continue;
    }

    const body = fill(rawBody, row, col);
    if (UNFILLED.test(body)) {
      setCell(sheet, r, col.Status, 'unfilled placeholder');
      continue;
    }

    const email = String(row[col.Email] || '').trim();
    const subject = touch === 0
      ? fill(String(row[col.Subject]), row, col)
      : 'Re: ' + fill(String(row[col.Subject]), row, col);

    if (DRY_RUN) {
      Logger.log('[dry run] ' + email + ' | ' + subject + '\n' + body + '\n---');
      setCell(sheet, r, col.Status, 'dry run touch ' + (touch + 1));
      sent++;
      continue;
    }

    let newThreadId = threadId;
    if (touch === 0) {
      newThreadId = GmailApp.createDraft(email, subject, body)
                            .send().getThread().getId();
    } else {
      // Reply into the same thread so the follow-up lands under the original.
      GmailApp.getThreadById(threadId).replyAll(body);
    }

    setCell(sheet, r, col.ThreadId, newThreadId);
    setCell(sheet, r, col.LastSent, new Date());
    setCell(sheet, r, col.Touch, touch + 1);
    setCell(sheet, r, col.Status,
            touch + 1 >= 3 ? 'done' : 'sent touch ' + (touch + 1));
    sent++;

    Utilities.sleep(3000 + Math.floor(Math.random() * 5000));
  }

  Logger.log('Processed ' + sent + ' rows as ' + Session.getActiveUser().getEmail());
}


/** Replace {{placeholders}} with values from the row. */
function fill(text, row, col) {
  return text.replace(/\{\{\s*(\w+)\s*\}\}/g, function (whole, key) {
    const header = {
      firstName: 'FirstName', firstname: 'FirstName',
      channel: 'Channel', subs: 'Subs', subscribers: 'Subs',
      cadence: 'Cadence', country: 'Country', handle: 'Handle',
    }[key] || key;
    const index = col[header];
    if (index === undefined) return whole;
    const value = String(row[index] || '').trim();
    return value || whole;
  });
}


function hasReply(threadId) {
  try {
    const thread = GmailApp.getThreadById(threadId);
    if (!thread) return false;
    const me = Session.getActiveUser().getEmail().toLowerCase();
    return thread.getMessages()
                 .some(m => m.getFrom().toLowerCase().indexOf(me) === -1);
  } catch (err) {
    Logger.log('reply check failed for ' + threadId + ': ' + err);
    return false;
  }
}


function daysSince(value) {
  if (!value) return 999;
  const then = new Date(value).getTime();
  if (isNaN(then)) return 999;
  return (Date.now() - then) / (1000 * 60 * 60 * 24);
}


function setCell(sheet, rowIndex, colIndex, value) {
  sheet.getRange(rowIndex + 1, colIndex + 1).setValue(value);
}
