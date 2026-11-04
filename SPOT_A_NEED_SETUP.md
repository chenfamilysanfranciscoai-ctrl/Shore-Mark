# Spot a Need: setup and moderation guide

Spot a Need lets anyone send photos of a place that needs help. Nothing is public until you approve it. Approved reports appear on the Needs Board (needs.html), where organizations can offer to host an event.

It uses Supabase (free plan) for the database and photo storage. About 20 minutes to set up.

## One-time setup

1. Go to supabase.com, sign up, and create a new project. Pick any name, set a database password (save it somewhere private), and choose a US West region.
2. In the project, open **SQL Editor > New query**, paste the whole contents of `supabase/schema.sql`, and click **Run**. It should say "Success". Running it again later is harmless.
3. Turn off public sign-ups: **Authentication > Sign In / Providers**, then switch off "Allow new users to sign up". (Nobody needs an account except you.)
4. Create your admin login: **Authentication > Users > Add user > Create new user**. Use an email you check and a long password. Tick "Auto confirm user".
5. Make that user an admin. In **SQL Editor** run this, with your admin email in place of the example:

   `insert into public.admins (user_id) select id from auth.users where email = 'YOUR-ADMIN-EMAIL';`

6. Connect the website: **Project Settings > API**. Copy the **Project URL** and the **anon public** key into `supabase-config.js`. Never paste the "service_role" key anywhere.
7. Upload the folder to the Shoremark repo as usual. Open `admin.html` on the live site (it is not linked from the menu), sign in, and you should see an empty queue.

## Testing it yourself (all free)

1. Open `spot.html` on your phone, add a photo, fill in the form and send.
2. Open `admin.html`, sign in, and approve it. Check it appears on `needs.html`.
3. Click "My group could host here" and send a test. Check it shows under "Groups that want to host" in the admin page.
4. Delete your test report from the admin page ("Delete").

## Moderation checklist (before you click Approve)

- No identifiable people, faces or license plates in any photo. If there are, reject.
- No names, phone numbers, emails or home addresses in the description.
- The site looks like public land, a beach, creek, trail or street. Reject reports about someone's private property or a specific neighbor.
- Do not approve anything that encourages touching needles, chemicals or animals. Reports about hazards can be approved if the text says to leave it to the land manager.
- Reject spam, jokes and anything that does not show a real environmental problem.
- "Reject and delete" removes the report and its photos for good.

The "Live on the board" tab lets you record which group is organizing a cleanup, mark a site "Cleaned up", or take a report off the board.

## What is and is not protected

- The public key can only add a report that starts as pending, and read approved reports. It cannot read pending reports, contact details of organizations, or anything else.
- Public coordinates are rounded to about 100 meters. Exact coordinates are visible only in the admin page.
- Photos are shrunk and re-saved in the browser, which removes hidden data such as GPS.
- Uploaded photos are stored with random file names in a public photo folder. A photo of a still-pending report can be seen by anyone who has its exact link, which only the sender and you have. If you reject a report, its photos are deleted.
- The database stops accepting new reports when 100 are already waiting for review, so a flood of junk cannot fill the free plan. Clear the queue to reopen it.
- There is no CAPTCHA. A hidden form field catches simple bots. If spam becomes a problem, tell me and I will add one.

## Good to know

- Supabase free projects can pause after a period of no activity. If the form stops working, open the Supabase dashboard and restore the project.
- If a photo uploads but the report fails, a stray photo file can be left in storage. They are small and can be deleted from **Storage > report-photos**.
- Organizations that offer to host leave their name and email. Only you can see these. Reply from an email you are comfortable using, and keep it professional.
