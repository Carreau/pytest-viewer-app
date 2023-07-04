"""
This module contain github types for the github api

The goal is to only profide the types that are needed for this project for now, 

None of the goals are to expose better API.

When possbile we use the newtype pattern to make sure that we don't mix up the types.
"""

from dataclasses import dataclass, fields
from typing import NewType, List, Dict, Any, Optional


CommitSha = NewType("CommitSha", str)
RunId = NewType("RunId", int)
PullRequestNumber = NewType("PullRequestNumber", int)


class _Base:
    @classmethod
    def from_json(cls, data):
        """
        For now drop fields we do not need
        """
        f_data = {}
        fields_names = [f.name for f in fields(cls)]
        for key in data.keys():
            if key in fields_names:
                f = [f for f in fields(cls) if f.name == key][0]
                if isinstance(f.type, type) and issubclass(f.type, _Base):
                    f_data[f.name] = f.type.from_json(data[f.name])
                else:
                    f_data[f.name] = data[f.name]

        return cls(**{name: f_data[name] for name in f_data.keys()})


@dataclass
class Head(_Base):
    ref: str
    sha: CommitSha


@dataclass
class PullRequest(_Base):
    number: PullRequestNumber
    title: str
    head: Head


@dataclass
class WorkflowRun(_Base):
    id: int
    name: str
    head_branch: str
    head_sha: CommitSha
    status: str
    conclusion: str
    url: str
    html_url: str
    created_at: str
    updated_at: str
    artifacts_url: CommitSha
