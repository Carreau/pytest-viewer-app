- [ ] Provide a script to ping collect_artifact_metadata route from github actions
- [ ] Add a github API call to get the artifact from the run id directly (instead of crawling) : `/repos/{owner}/{repo}/actions/runs/{run_id}/artifacts`, https://docs.github.com/en/rest/actions/artifacts?apiVersion=2022-11-28#list-workflow-run-artifacts

- [ ] Provide a route for the client to list all known org/repo/run_id/pull_number known to the db (essentially select from action_run)

- [ ] Consume that API in the client to list known PRs

- [ ] Compact json report with jq before uploading it to the artifacts
