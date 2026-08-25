/**
 * Gmail outreach sequencer — Google Apps Script.
 *
 * Runs the three-touch sequence from a Google Sheet: initial email, follow-up
 * after 3 days, follow-up after 4 days, stopping the moment someone replies.
 *
 * SETUP
 *  1. Import all_creators.csv into a Google Sheet, tab named "Outreach".
 *  2. Add these columns (exact headers):
 *       Email | FirstName | Channel | Subscribers | Cadence | Opener | Proof
 *       Status | ThreadId | LastSent | Touch
 *  3. Extensions > Apps Script, paste this file, Save.
 *  4. Run `run` once manually to grant permissions.
 *  5. Triggers > Add Trigger > run > Time-driven > Day timer > 9am-10am.
 *
 * The script sends at most DAILY_CAP per run and skips any row without an
 * Opener, which keeps the personalisation manual on purpose.
 */

const SHEET_NAME = 'Outreach';
const DAILY_CAP = 12;          // Gmail allows far more; low volume protects the domain.
const FOLLOWUP_1_AFTER_DAYS = 3;
const FOLLOWUP_2_AFTER_DAYS = 4;
const YOUR_FIRST_NAME = 'JB';
const DRY_RUN = true;          // Set false to actually send. Leave true for the first pass.


function run() {
  const sheet = SpreadsheetApp.getActive().getSheetByName(SHEET_NAME);
  const data = sheet.getDataRange().getValues();
  const header = data[0];
  const col = {};
  header.forEach((name, i) => col[String(name).trim()] = i);

  ['Email', 'FirstName', 'Channel', 'Opener', 'Status', 'ThreadId', 'LastSent', 'Touch']
    .forEach(name => {
      if (col[name] === undefined) throw new Error('Missing column: ' + name);
    });

  let sent = 0;

  for (let r = 1; r < data.length && sent < DAILY_CAP; r++) {
    const row = data[r];
    const email = String(row[col.Email] || '').trim();
    const status = String(row[col.Status] || '').trim();

    if (!email || status === 'done' || status === 'replied' || status === 'skip') continue;

    // No hook, no send. A merged template with a generic opener is the
    // fastest way to burn a list.
    if (!String(row[col.Opener] || '').trim()) {
      setCell(sheet, r, col.Status, 'needs opener');
      continue;
    }

    const touch = Number(row[col.Touch] || 0);
    const threadId = String(row[col.ThreadId] || '').trim();

    // Someone replying ends the sequence, whatever stage it is at.
    if (threadId && hasReply(threadId)) {
      setCell(sheet, r, col.Status, 'replied');
      continue;
    }

    if (touch > 0) {
      const waited = daysSince(row[col.LastSent]);
      const needed = touch === 1 ? FOLLOWUP_1_AFTER_DAYS : FOLLOWUP_2_AFTER_DAYS;
      if (waited < needed) continue;
    }

    const fields = {
      firstName: String(row[col.FirstName] || '').trim(),
      channel: String(row[col.Channel] || '').trim(),
      subscribers: formatCount(row[col.Subscribers]),
      cadence: String(row[col.Cadence] || '').trim(),
      opener: String(row[col.Opener] || '').trim(),
      proof: String(row[col.Proof] || '').trim(),
    };

    const body = buildBody(touch, fields);
    const subject = touch === 0
      ? 'built something for ' + fields.channel
      : 'Re: built something for ' + fields.channel;

    if (DRY_RUN) {
      Logger.log('[dry run] ' + email + ' | ' + subject + '\n' + body + '\n---');
      setCell(sheet, r, col.Status, 'dry run touch ' + (touch + 1));
      sent++;
      continue;
    }

    let newThreadId = threadId;
    if (touch === 0) {
      const draft = GmailApp.createDraft(email, subject, body);
      const message = draft.send();
      newThreadId = message.getThread().getId();
    } else {
      // Reply into the same thread so follow-ups stay in one conversation.
      GmailApp.getThreadById(threadId).replyAll(body);
    }

    setCell(sheet, r, col.ThreadId, newThreadId);
    setCell(sheet, r, col.LastSent, new Date());
    setCell(sheet, r, col.Touch, touch + 1);
    setCell(sheet, r, col.Status, touch + 1 >= 3 ? 'done' : 'sent touch ' + (touch + 1));
    sent++;

    Utilities.sleep(2000 + Math.floor(Math.random() * 4000));
  }

  Logger.log('Processed ' + sent + ' rows.');
}


function buildBody(touch, f) {
  if (touch === 0) {
    return [
      'Hey ' + f.firstName + ',',
      '',
      f.opener,
      '',
      cadenceLine(f),
      '',
      f.proof,
      '',
      'I put together a 90 second breakdown of one of your recent videos - three',
      'specific places where the pacing and sound are costing you retention, with',
      'the fixes. No pitch in it, just the edit notes.',
      '',
      'Want me to send it over?',
      '',
      YOUR_FIRST_NAME,
    ].join('\n');
  }

  if (touch === 1) {
    return [
      'Hey ' + f.firstName + ',',
      '',
      'Just bumping this in case it got buried.',
      '',
      'The reason I reached out: most creators at your size are still cutting their',
      'own videos, and it quietly caps how often they can post.',
      '',
      'I edit long form YouTube with sound leading every choice - story structure,',
      'pacing, and audio, which is where most retention drops actually come from.',
      '',
      'That 90 second breakdown of your recent video is still sitting here.',
      '',
      'Want me to send it over?',
      '',
      YOUR_FIRST_NAME,
    ].join('\n');
  }

  return [
    'Hey ' + f.firstName + ',',
    '',
    'Reaching out one last time.',
    '',
    'I know you probably get pitched by editors constantly, which is why I would',
    'rather just show you the actual work than describe it.',
    '',
    'The breakdown shows exactly what I would change in one of your videos and why -',
    'three cuts, the sound underneath them, and what it does to the drop-off.',
    '',
    'Want me to send it over?',
    '',
    YOUR_FIRST_NAME,
  ].join('\n');
}


/**
 * The "editing is eating your week" angle is false for a channel that already
 * ships weekly, and they will notice. Swap the line instead of the whole email.
 */
function cadenceLine(f) {
  if (f.cadence === 'weekly') {
    return 'You are posting weekly and holding it, which is the hard part. The '
         + 'question is what you would make if the edit was not yours to do.';
  }
  return 'I noticed you are posting ' + f.cadence + '. For a channel at '
       + f.subscribers + ' that usually means you are editing them yourself, and '
       + 'the edit is what is eating the month.';
}


function hasReply(threadId) {
  try {
    const thread = GmailApp.getThreadById(threadId);
    if (!thread) return false;
    const me = Session.getActiveUser().getEmail().toLowerCase();
    return thread.getMessages().some(m => {
      const from = m.getFrom().toLowerCase();
      return from.indexOf(me) === -1;
    });
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


function formatCount(value) {
  const n = Number(String(value).replace(/[^\d]/g, ''));
  if (!n) return '';
  if (n >= 1000000) return (n / 1000000).toFixed(1).replace(/\.0$/, '') + 'M';
  if (n >= 1000) return Math.round(n / 1000) + 'k';
  return String(n);
}


function setCell(sheet, rowIndex, colIndex, value) {
  sheet.getRange(rowIndex + 1, colIndex + 1).setValue(value);
}
