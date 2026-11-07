# Phase 1B+ — Auth and memory rollout, Miniai Supabase

**Project:** https://gkdaxtnlwojggdqitsex.supabase.co  
**Branch:** feature/phase1b-supabase-multiuser  
**Date:** 2026-11-08  
**Status:** Schema applied + RLS audited. Browser integration implemented in review branch. Google provider, production SMTP, phone hook and end-to-end real signup still require provider validation.

## Migration verified in linked Supabase project

An applied migration named \`mini_identity_and_memory_v1\` created four empty tables:
- \`public.mini_profiles\` — per-user, explicitly consented onboarding profile, bound to auth.users.
- \`public.mini_memories\` — per-user explicitly confirmed facts, optional expiration.
- \`public.mini_conversations\` — optional consented text history, initially empty.
- \`public.mini_messages\` — short text messages, composite foreign key prevents attaching a message to another user's conversation.

All four tables have RLS enabled. Policies for SELECT/INSERT/UPDATE/DELETE require \`(select auth.uid()) = user_id\`. \`anon\` has no table access. Only \`authenticated\` and \`service_role\` are granted DML; the client uses the publishable key, never the service role. No user records or actual audio have been inserted.

Security advisors originally flagged public EXECUTE permission on \`public.rls_auto_enable()\`, a privileged helper. That permission was revoked for PUBLIC, anon and authenticated; subsequent advisor scan reported zero findings.

## Browser integration

The feature branch adds:
- Official pinned \`@supabase/supabase-js\` v2.119.0 (verify deployment's npm install/build; this repo has no existing npm lockfile).
- \`/api/auth/public-config\`, returning only Vercel-configured project URL and enabled **publishable** key; never a worker token or service-role key.
- Real Supabase PKCE Google OAuth.
- Real emailed OTP request and \`verifyOtp({email,token,type:'email'})\` verification.
- WhatsApp phone sign-in code path, **fail closed** unless \`MINI_SCRIWO_OTP_VERIFIED=true\`. That flag has not been enabled. Supabase Auth Send SMS Hook must be configured to send through a verified Scriwo API contract before enabling it. Do not use a mock code or put Scriwo credentials in frontend.
- Separate Supabase session from the existing owner-only Google session. Private NFC voice service is NOT yet enabled for arbitrary public users.
- Profile memory save/forget, confirmed fact save/list/delete, and account-specific browser data cleanup. Session data is resolved via Supabase Auth, never a user ID supplied by the browser.

Vercel preview variables for this branch have been configured: MINI_SUPABASE_URL, MINI_SUPABASE_PUBLISHABLE_KEY, MINI_SCRIWO_OTP_VERIFIED=false. **They are preview-only and not production enabled.**

## Authentication provider prerequisites in Supabase dashboard

1. Auth > URL Configuration: set Site URL and approved redirect origins to the *actual* reviewed preview/production URLs. Do not enable wildcard OAuth redirects for untrusted hosts.
2. Auth > Providers > Google: enable with Google OAuth client ID and secret. Create Google OAuth allowed origins and provider redirect URI. Test with an account other than the owner.
3. Auth > Email: configure a production SMTP sender. If an actual numeric OTP is desired, the confirmation email template MUST include \`{{ .Token }}\` rather than only \`{{ .ConfirmationURL }}\`. Validate delivery, expiration, resends, rate limits and account linking.
4. Auth > Phone: do not enable public OTP until Scriwo's API, approved WhatsApp template, phone E.164 formatting, error reporting and Send SMS Hook secret validation are reviewed. The helper explicitly uses Supabase SMS OTP with the verified Send SMS Hook; it does NOT assume Twilio's provider-specific \`channel:'whatsapp'\` works for Scriwo.
5. Enable abuse protections, appropriate email/OTP cooldowns, redirect allowlists and security monitoring.

Official docs:
- https://supabase.com/docs/guides/auth/social-sign-in/auth-google
- https://supabase.com/docs/guides/auth/auth-email-passwordless
- https://supabase.com/docs/guides/auth/auth-hooks/send-sms-hook
- https://supabase.com/docs/guides/database/postgres/row-level-security

## Mandatory security acceptance before merging or enabling public signup

- [ ] GitHub Actions \`npm test\` and \`npm run build\` pass for this branch after dependency installation.
- [ ] First account: Google OAuth completes after PKCE redirect, sessions persist and sign out correctly.
- [ ] Second independent account: real OTP delivered and verified; wrong/expired codes rejected.
- [ ] Two users cannot select/update/delete each other's mini_profiles, mini_memories, conversations or messages (negative RLS tests).
- [ ] Browser previous-demo profile does NOT appear as the new authenticated user's profile.
- [ ] Saving a memory requires individual opt-in; deleting it and the profile works.
- [ ] Network inspect: no \`service_role\` key, worker bearer secret, custom voice sample or OTP appears in frontend JS or logs.
- [ ] WhatsApp sending stays OFF until verified end-to-end with Scriwo.
- [ ] All hosted voice endpoints still reject non-owner sessions; separate per-user voice session authentication is a later milestone.
- [ ] Existing NFC private voice worker still healthy and unchanged.

**Rollback:** revert feature branch UI or disable preview MINI_SUPABASE_URL. The applied empty RLS tables can remain unused; do not drop them just to roll back the frontend. Never force-replace the current NFC service.

## Pocket TTS experiment decision

Agent-measured catalog Pocket TTS first chunks were 152–255 ms with ~0.46–0.87 RTF depending on threads. The available catalog voices \`alba\` and \`george\` are NOT the owner's two approved Mini voices. Do NOT replace Chatterbox with those analogues.

To test custom voice, the model operator must accept gated model terms at https://huggingface.co/kyutai/pocket-tts and authenticate locally with a private Hugging Face credential via official tooling. Then benchmark both owner-authorized reference clips and score voice similarity with eyes-closed listening against Chatterbox. Keep the live Mini service unchanged until custom voice fidelity and first-*meaningful*-reply latency pass.
