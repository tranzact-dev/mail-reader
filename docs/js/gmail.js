const LABEL_NAME = "_親族/親父";
const DISCOVERY_DOC = "https://www.googleapis.com/discovery/v1/apis/gmail/v1/rest";
const SCOPES = "https://www.googleapis.com/auth/gmail.modify";

class GmailClient {
  constructor(clientId) {
    this.clientId = clientId;
    this.tokenClient = null;
  }

  async init() {
    await new Promise((resolve) => gapi.load("client", resolve));
    await gapi.client.init({ discoveryDocs: [DISCOVERY_DOC] });
    this.tokenClient = google.accounts.oauth2.initTokenClient({
      client_id: this.clientId,
      scope: SCOPES,
      callback: () => {},
    });
  }

  requestAuth() {
    return new Promise((resolve, reject) => {
      this.tokenClient.callback = (resp) => {
        if (resp.error) {
          reject(new Error(resp.error));
        } else {
          resolve(resp);
        }
      };
      this.tokenClient.requestAccessToken({ prompt: "" });
    });
  }

  signOut() {
    const token = gapi.client.getToken();
    if (token) {
      google.accounts.oauth2.revoke(token.access_token);
      gapi.client.setToken(null);
    }
  }

  async _apiCall(fn) {
    try {
      return await fn();
    } catch (e) {
      if (e.status === 401) {
        await this.requestAuth();
        return await fn();
      }
      throw e;
    }
  }

  async getLabelId() {
    const resp = await this._apiCall(() =>
      gapi.client.gmail.users.labels.list({ userId: "me" })
    );
    const label = resp.result.labels.find((l) => l.name === LABEL_NAME);
    return label ? label.id : null;
  }

  async getUnreadMessagesGrouped(labelId) {
    const resp = await this._apiCall(() =>
      gapi.client.gmail.users.messages.list({
        userId: "me",
        labelIds: [labelId],
        q: "is:unread",
      })
    );
    const messages = resp.result.messages || [];
    const threadMap = new Map();
    for (const msg of messages) {
      if (!threadMap.has(msg.threadId)) {
        threadMap.set(msg.threadId, []);
      }
      threadMap.get(msg.threadId).push(msg);
    }
    const groups = [];
    for (const [, msgs] of threadMap) {
      msgs.reverse();
      groups.push(msgs);
    }
    return groups;
  }

  async getMessageDetail(msgId) {
    const resp = await this._apiCall(() =>
      gapi.client.gmail.users.messages.get({
        userId: "me",
        id: msgId,
        format: "full",
      })
    );
    const msg = resp.result;
    const headers = msg.payload.headers;
    let subject = "", sender = "", dateStr = "";
    for (const h of headers) {
      const name = h.name.toLowerCase();
      if (name === "subject") subject = h.value;
      else if (name === "from") sender = h.value;
      else if (name === "date") dateStr = h.value;
    }
    const body = extractBody(msg.payload);
    return {
      id: msgId,
      sender: parseSenderName(sender),
      subject,
      date: formatDate(dateStr),
      hasAttachment: checkAttachments(msg.payload),
      bodyClean: cleanBodyForReading(body),
    };
  }

  async markAsRead(msgId) {
    await this._apiCall(() =>
      gapi.client.gmail.users.messages.modify({
        userId: "me",
        id: msgId,
        resource: { removeLabelIds: ["UNREAD"] },
      })
    );
  }

  async fetchAllUnread() {
    const labelId = await this.getLabelId();
    if (!labelId) return { threads: [], totalMsgs: 0, error: "label-not-found" };
    const groups = await this.getUnreadMessagesGrouped(labelId);
    if (groups.length === 0) return { threads: [], totalMsgs: 0 };
    const threads = [];
    let totalMsgs = 0;
    for (const group of groups) {
      const emails = [];
      for (const ref of group) {
        const detail = await this.getMessageDetail(ref.id);
        emails.push(detail);
        totalMsgs++;
      }
      threads.push(emails);
    }
    return { threads, totalMsgs };
  }
}
