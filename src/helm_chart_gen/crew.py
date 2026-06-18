from crewai import Agent, Crew, Process, Task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.project import CrewBase, agent, crew, task

from helm_chart_gen.tools.custom_tool import (
    HelmChartWriterTool,
    HelmValidationTool,
    RepositoryCloneTool,
    RepositoryScanTool,
    SecretRedactionTool,
)


@CrewBase
class HelmChartGen:
    """CrewAI Studio-ready Helm chart generator crew."""

    agents: list[BaseAgent]
    tasks: list[Task]

    @agent
    def repository_scanner(self) -> Agent:
        return Agent(
            config=self.agents_config["repository_scanner"],  # type: ignore[index]
            tools=[RepositoryCloneTool(), RepositoryScanTool(), SecretRedactionTool()],
            verbose=True,
        )

    @agent
    def application_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config["application_analyst"],  # type: ignore[index]
            tools=[SecretRedactionTool()],
            verbose=True,
        )

    @agent
    def kubernetes_expert(self) -> Agent:
        return Agent(
            config=self.agents_config["kubernetes_expert"],  # type: ignore[index]
            tools=[SecretRedactionTool()],
            verbose=True,
        )

    @agent
    def helm_generator(self) -> Agent:
        return Agent(
            config=self.agents_config["helm_generator"],  # type: ignore[index]
            tools=[HelmChartWriterTool(), SecretRedactionTool()],
            verbose=True,
        )

    @agent
    def security_reviewer(self) -> Agent:
        return Agent(
            config=self.agents_config["security_reviewer"],  # type: ignore[index]
            tools=[SecretRedactionTool()],
            verbose=True,
        )

    @agent
    def helm_validator(self) -> Agent:
        return Agent(
            config=self.agents_config["helm_validator"],  # type: ignore[index]
            tools=[HelmValidationTool(), SecretRedactionTool()],
            verbose=True,
        )

    @agent
    def human_approval_coordinator(self) -> Agent:
        return Agent(
            config=self.agents_config["human_approval_coordinator"],  # type: ignore[index]
            tools=[SecretRedactionTool()],
            verbose=True,
        )

    @task
    def repository_scan_task(self) -> Task:
        return Task(
            config=self.tasks_config["repository_scan_task"],  # type: ignore[index]
        )

    @task
    def application_analysis_task(self) -> Task:
        return Task(
            config=self.tasks_config["application_analysis_task"],  # type: ignore[index]
            context=[self.repository_scan_task()],
        )

    @task
    def kubernetes_requirements_task(self) -> Task:
        return Task(
            config=self.tasks_config["kubernetes_requirements_task"],  # type: ignore[index]
            context=[self.application_analysis_task()],
        )

    @task
    def helm_generation_task(self) -> Task:
        return Task(
            config=self.tasks_config["helm_generation_task"],  # type: ignore[index]
            context=[self.kubernetes_requirements_task()],
        )

    @task
    def security_review_task(self) -> Task:
        return Task(
            config=self.tasks_config["security_review_task"],  # type: ignore[index]
            context=[self.helm_generation_task()],
        )

    @task
    def helm_validation_task(self) -> Task:
        return Task(
            config=self.tasks_config["helm_validation_task"],  # type: ignore[index]
            context=[self.helm_generation_task(), self.security_review_task()],
        )

    @task
    def human_approval_task(self) -> Task:
        return Task(
            config=self.tasks_config["human_approval_task"],  # type: ignore[index]
            context=[
                self.repository_scan_task(),
                self.application_analysis_task(),
                self.kubernetes_requirements_task(),
                self.helm_generation_task(),
                self.security_review_task(),
                self.helm_validation_task(),
            ],
            human_input=True,
            output_file="output/human_approval_summary.md",
        )

    @crew
    def crew(self) -> Crew:
        """Creates the HelmChartGen crew."""
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
        )
