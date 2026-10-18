import type { Metadata } from "next"

export const metadata: Metadata = { title: "Privacy Policy" }

// Template text: replace every highlighted placeholder and have a lawyer review it before relying on it.
export default function PrivacyPage() {
  return (
    <article className="legal-doc">


<h1>Privacy Policy</h1>
<p className="meta">Effective date: 14 October 2026</p>

<nav className="toc" aria-label="Contents"><strong>Contents</strong><ol>
<li><a href="#who">Who we are</a></li><li><a href="#collect">What we collect</a></li><li><a href="#use">How we use it</a></li><li><a href="#google">Google user data</a></li>
<li><a href="#share">Who we share it with</a></li><li><a href="#access">Who can see your documents</a></li><li><a href="#cookies">Cookies</a></li><li><a href="#security">Security</a></li>
<li><a href="#retention">Retention and deletion</a></li><li><a href="#rights">Your choices and rights</a></li><li><a href="#transfers">Where data is processed</a></li><li><a href="#children">Children</a></li><li><a href="#changes">Changes</a></li><li><a href="#contact">Contact</a></li>
</ol></nav>

<p>This policy explains what information Amber (&ldquo;Amber&rdquo;, &ldquo;we&rdquo;, &ldquo;us&rdquo;) handles when you use our service, why, and the choices you have. Amber helps teams search and ask questions across documents stored in Google Drive.</p>

<h2 id="who">1. Who we are</h2>
<p>Amber is a personal hobby project, not a company. It is built and operated by Anushka Singh and Justin Dsouza, as individuals. For privacy questions, write to <a href="mailto:anushka.singh098@gmail.com">anushka.singh098@gmail.com</a>.</p>
<p>If your employer or organization gives you access to Amber, your organization decides which documents are added and who can see them. For that content we act on the organization&rsquo;s instructions, and you should also read its own policies.</p>

<h2 id="collect">2. What we collect</h2>
<div className="table-scroll"><table>
<thead><tr><th>Category</th><th>What it includes</th><th>Where it comes from</th></tr></thead>
<tbody>
<tr><td>Account information</td><td>Name, email address, profile picture, Google account ID, and your Google Workspace domain (if any)</td><td>Google sign-in</td></tr>
<tr><td>Documents you add</td><td>Files you upload or pick from Google Drive, plus their names, types, sizes and Drive link</td><td>You</td></tr>
<tr><td>Content we derive</td><td>Text extracted from your files, split into passages, and numeric &ldquo;embeddings&rdquo; of each passage used for search</td><td>Generated from your documents</td></tr>
<tr><td>Organization and sharing</td><td>Collections, tags, and the list of people or domains each file is shared with</td><td>You, and Google Drive sharing for picked files</td></tr>
<tr><td>Google Drive connection</td><td>A refresh token that lets Amber keep working with the files you allowed. It is stored encrypted</td><td>Google sign-in</td></tr>
<tr><td>Activity records</td><td>Security and audit entries: what action was taken (for example, sharing a file or an administrator changing a role), by whom, when, and from which IP address</td><td>Generated when you use Amber</td></tr>
<tr><td>Questions and answers</td><td>The questions you ask and the answers produced, when those features are used</td><td>You</td></tr>
</tbody></table></div>
<p>We do not ask for payment card details on this website, and the marketing website does not use analytics or advertising trackers.</p>

<h2 id="use">3. How we use it</h2>
<ul>
<li>To sign you in and keep your session secure.</li>
<li>To read, index and search the documents you add, and to answer your questions using only documents you are allowed to access.</li>
<li>To save uploads to your Google Drive and keep sharing in Drive and Amber in step, when you ask us to.</li>
<li>To let administrators of your Amber workspace manage users and review document access.</li>
<li>To detect abuse, investigate problems, keep audit records, and meet legal obligations.</li>
<li>To maintain and improve reliability and performance of the service.</li>
</ul>
<p>We do not sell your personal information, and we do not use your documents for advertising.</p>

<h2 id="google">4. Google user data</h2>
<p>Amber signs you in with Google and, with your permission, connects to Google Drive. We request these permissions:</p>
<ul>
<li><strong>Basic profile and email</strong> to identify your account.</li>
<li><strong>Google Drive &ldquo;drive.file&rdquo;</strong> to (a) create the &ldquo;Amber Uploads&rdquo; folder and save files you upload there, (b) read the files you choose with the Google file picker, and (c) view and change the sharing settings of those files when you ask us to. This permission does not let Amber see other files in your Drive.</li>
</ul>
<div className="callout"><p>Amber&rsquo;s use and transfer to any other app of information received from Google APIs will adhere to the <a href="https://developers.google.com/terms/api-services-user-data-policy">Google API Services User Data Policy</a>, including the Limited Use requirements.</p></div>
<p>In line with those requirements, we use Google user data only to provide and improve the user-facing features described in this policy. We do not sell it, do not use it for advertising, do not transfer it to others except as needed to provide the service, comply with law, or with your consent, and do not allow people to read it except when you ask for help, for security investigations, to comply with law, or when it is aggregated and anonymized. We do not use Google user data to develop or train generalized AI models.</p>
<p>You can remove Amber&rsquo;s access at any time from your Amber profile (&ldquo;Disconnect Drive&rdquo;) or from your Google Account&rsquo;s third-party access settings.</p>

<h2 id="share">5. Who we share it with</h2>
<p>We share information only with service providers that help us run Amber, under terms that limit how they may use it:</p>
<ul>
<li><strong>Google</strong>: sign-in (Firebase Authentication and Google OAuth), Google Drive, and Google Cloud hosting (compute, database, key management and secrets).</li>
<li><strong>Google Gemini API</strong>: passages of your documents and your questions are sent to Gemini to create embeddings and, when answering is enabled, to write answers. We use the paid tier of the API. <mark className="todo">[Confirm Google&rsquo;s current paid-tier terms say customer content is not used to train its models, and keep this sentence only if true.]</mark></li>
</ul>
<p>We may disclose information if required by law or to protect rights, safety and security. If Amber is involved in a merger or sale, we will tell you before your information becomes subject to a different policy.</p>

<h2 id="access">6. Who can see your documents inside Amber</h2>
<ul>
<li><strong>You</strong> see files you own or that were shared with you, individually or through your organization.</li>
<li><strong>People you share with</strong> can find and receive answers from those files.</li>
<li><strong>Administrators</strong> of your Amber workspace can see file names, owners, sharing settings, processing status and user lists. Amber does not provide administrators a way to read the text of files they cannot open themselves.</li>
<li><strong>Our staff</strong> do not access document content as part of normal operations. Access is limited to what is needed for support you request, security, or legal compliance.</li>
</ul>
<p>When you share a file in Amber, we also change its sharing in Google Drive, and Google may email the people you share with. Sharing with &ldquo;your organization&rdquo; makes the file visible to everyone in your Google Workspace domain.</p>

<h2 id="cookies">7. Cookies</h2>
<p>The Amber app uses only essential cookies: a session cookie to keep you signed in, a security cookie that protects against cross-site request forgery, and a short-lived cookie used during Google sign-in. These cannot be switched off without breaking sign-in. We do not use advertising or cross-site tracking cookies. This marketing website sets no cookies.</p>

<h2 id="security">8. Security</h2>
<ul>
<li>All traffic uses HTTPS.</li>
<li>Google Drive refresh tokens are encrypted before storage using keys managed in Google Cloud Key Management Service.</li>
<li>Access to documents is checked on the server for every request, and changes by users and administrators are recorded in an audit log.</li>
<li>Secrets are kept in a managed secret store, not in source code.</li>
</ul>
<p>No system is perfectly secure. If we learn of a breach affecting your information, we will notify you and any required authorities as the law requires.</p>

<h2 id="retention">9. Retention and deletion</h2>
<ul>
<li><strong>Deleting a document</strong> in Amber removes its extracted text and embeddings. It does not delete the original file from Google Drive.</li>
<li><strong>Disconnecting Drive</strong> deletes the stored token and asks Google to revoke it.</li>
<li><strong>Removing a user</strong> (an administrator action) deletes their account and everything they own in Amber, including documents, collections and tokens.</li>
<li><strong>Audit and security records</strong> are kept for as long as needed for security and accountability, and then deleted and may refer to a user by email address and IP address.</li>
<li><strong>Backups</strong> of our database are kept according to Google Cloud&rsquo;s backup schedule for the database and then expire.</li>
</ul>
<p>To ask for deletion of your account, contact your workspace administrator or write to us.</p>

<h2 id="rights">10. Your choices and rights</h2>
<p>Depending on where you live, you may have the right to access, correct, delete, export or restrict use of your personal information, to object to certain processing, and to complain to a data protection authority. To use these rights, contact us at the address above. We may need to verify your identity, and for content your organization controls we may refer you to your administrator.</p>

<h2 id="transfers">11. Where data is processed</h2>
<p>Amber is hosted on Google Cloud in Mumbai, India. Google may process data, including Gemini API requests, in other countries. By using Amber you understand your information may be transferred to and processed in countries other than your own, with protections consistent with this policy.</p>

<h2 id="children">12. Children</h2>
<p>Amber is built for workplaces and is not intended for anyone under 16. We do not knowingly collect information from children. If you believe a child has provided information to us, contact us and we will delete it.</p>

<h2 id="changes">13. Changes to this policy</h2>
<p>We may update this policy. When we make material changes we will update the effective date and, where appropriate, notify you in the app or by email.</p>

<h2 id="contact">14. Contact</h2>
<p>Anushka Singh and Justin Dsouza (individuals)<br /><a href="mailto:anushka.singh098@gmail.com">anushka.singh098@gmail.com</a></p>

    </article>
  )
}
