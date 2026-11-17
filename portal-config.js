/* Public X-Stage portal configuration only.
 * Set URL + anon/publishable key AFTER provisioning a dedicated X-Stage backend.
 * NEVER publish Supabase service_role / secret keys in this file.
 */
window.XSTAGE_PORTAL_CONFIG = Object.freeze({
  supabaseUrl: "",
  supabasePublishableKey: ""
});
