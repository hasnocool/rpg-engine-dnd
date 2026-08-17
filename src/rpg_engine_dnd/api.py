"""FastAPI REST/WebSocket surface for the hosted v3 platform.

The v3 profile is knowledge-scoped by default. Omniscient state is available only when
an owner credential matches the campaign owner identifier supplied at creation.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from .browser import BROWSER_HTML
from .commands import Command, CreateEntity, DeleteEntity, PatchComponent, RemoveComponent, SetComponent
from .canonical import canonical_hash
from .compiler import RuleCompiler, RuleDocument
from .director import AdvancedAIDirector, DirectorObservation
from .distribution import ContentDistributionRegistry, PackageDependency, PackageRelease
from .events import Event
from .knowledge import KnowledgeView
from .lifecycle import CharacterBuild, CharacterLifecycle, ProgressionTrack, ResourcePool
from .orchestrator import Scene, SceneStatus
from .platform import ENGINE_API_VERSION, PUBLIC_API_INFO
from .studio import StudioProject
from .world_platform import RuleExecuteCommand, WorldPlatformEngine


class ScopedEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    sequence: int
    kind: str
    entity_id: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)


class CampaignRuntime:
    def __init__(self, campaign_id: str, seed: str, owner_id: str) -> None:
        self.campaign_id = campaign_id
        self.owner_id = owner_id
        self.platform = WorldPlatformEngine(seed=seed)
        self.engine = self.platform.core
        self.rules = self.platform.rules
        self.knowledge = self.platform.knowledge
        self.orchestrator = self.platform.orchestrator
        self.actor_owners: dict[str, str] = {}
        self.event_history: list[Event] = []
        self.lock = asyncio.Lock()
        self.subscribers: set[asyncio.Queue[Event]] = set()

    def is_owner(self, owner_id: str | None) -> bool:
        return owner_id is not None and owner_id == self.owner_id

    def can_view_actor(self, user_id: str | None, actor_id: str | None) -> bool:
        if actor_id is None or user_id is None:
            return False
        return self.actor_owners.get(actor_id) == user_id or actor_id == user_id

    def view(self, *, user_id: str | None, actor_id: str | None, owner_id: str | None) -> KnowledgeView:
        if self.is_owner(owner_id):
            return self.knowledge.omniscient_view(self.engine.world, owner_id or self.owner_id)
        if actor_id is not None and self.can_view_actor(user_id, actor_id):
            return self.knowledge.actor_view(self.engine.world, actor_id)
        return self.knowledge.spectator_view(self.engine.world)

    def scope_event(self, event: Event, *, user_id: str | None, actor_id: str | None, owner_id: str | None) -> ScopedEvent | None:
        if self.is_owner(owner_id):
            return ScopedEvent(
                sequence=event.sequence,
                kind=event.kind,
                entity_id=event.entity_id,
                payload=deepcopy(event.payload),
            )
        view = self.view(user_id=user_id, actor_id=actor_id, owner_id=owner_id)
        if event.entity_id is None:
            return ScopedEvent(sequence=event.sequence, kind=event.kind)
        if event.entity_id not in view.entities:
            return None
        payload = deepcopy(event.payload) if actor_id == event.entity_id else {}
        return ScopedEvent(
            sequence=event.sequence,
            kind=event.kind,
            entity_id=event.entity_id,
            payload=payload,
        )

    def _record_locked(self, event: Event) -> list[asyncio.Queue[Event]]:
        self.event_history.append(event)
        if event.entity_id is not None and event.entity_id in self.engine.world.entities:
            if event.entity_id in self.actor_owners:
                self.knowledge.ingest_perception(
                    event.entity_id,
                    self.engine.world.entities[event.entity_id],
                    sequence=event.sequence,
                )
        return list(self.subscribers)

    @staticmethod
    def _publish(event: Event, subscribers: list[asyncio.Queue[Event]]) -> None:
        for queue in subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # A slow client must never make an already-committed authoritative
                # mutation look like it failed. Keep the newest event; clients can
                # recover older sequences from the event-history endpoint.
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    continue
                queue.put_nowait(event)

    async def command(self, raw: dict[str, Any]) -> Event:
        kind = str(raw.get("kind"))
        command: Command
        if kind == "entity.create":
            command = CreateEntity.model_validate(raw)
        elif kind == "entity.delete":
            command = DeleteEntity.model_validate(raw)
        elif kind == "component.set":
            command = SetComponent.model_validate(raw)
        elif kind == "component.patch":
            command = PatchComponent.model_validate(raw)
        elif kind == "component.remove":
            command = RemoveComponent.model_validate(raw)
        else:
            raise ValueError(f"unsupported command kind: {raw.get('kind')}")
        async with self.lock:
            event = self.platform.handle(command)
            subscribers = self._record_locked(event)
        self._publish(event, subscribers)
        return event

    async def mutate_component(
        self,
        *,
        entity_id: str,
        component: str,
        command_id: str,
        mutator: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> tuple[Event, dict[str, Any]]:
        async with self.lock:
            entity = self.engine.world.entity(entity_id)
            current = deepcopy(entity.components.get(component, {}))
            value = mutator(current)
            event = self.platform.handle(
                SetComponent(
                    command_id=command_id,
                    entity_id=entity_id,
                    component=component,
                    value=value,
                )
            )
            subscribers = self._record_locked(event)
        self._publish(event, subscribers)
        return event, value

    async def execute_rule(self, command: RuleExecuteCommand) -> tuple[Event, dict[str, object]]:
        async with self.lock:
            event, result = self.platform.execute_rule(command)
            subscribers = self._record_locked(event)
        self._publish(event, subscribers)
        return event, result.model_dump(mode="json")


class CampaignService:
    def __init__(self) -> None:
        self._campaigns: dict[str, CampaignRuntime] = {}
        self._lock = asyncio.Lock()

    async def create(self, campaign_id: str, seed: str, owner_id: str) -> CampaignRuntime:
        async with self._lock:
            if campaign_id in self._campaigns:
                raise ValueError("campaign already exists")
            runtime = CampaignRuntime(campaign_id, seed, owner_id)
            self._campaigns[campaign_id] = runtime
            return runtime

    async def get(self, campaign_id: str) -> CampaignRuntime:
        async with self._lock:
            try:
                return self._campaigns[campaign_id]
            except KeyError as exc:
                raise KeyError(campaign_id) from exc


class StudioService:
    def __init__(self) -> None:
        self.projects: dict[str, StudioProject] = {}
        self.lock = asyncio.Lock()

    async def put(self, project: StudioProject) -> StudioProject:
        async with self.lock:
            self.projects[project.project_id] = project.model_copy(deep=True)
            return self.projects[project.project_id].model_copy(deep=True)

    async def get(self, project_id: str) -> StudioProject:
        async with self.lock:
            try:
                return self.projects[project_id].model_copy(deep=True)
            except KeyError as exc:
                raise KeyError(project_id) from exc

    async def mutate_snapshot(self, project_id: str) -> StudioProject:
        async with self.lock:
            project = self.projects[project_id]
            project.snapshot()
            return project.model_copy(deep=True)


class CreateCampaignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    campaign_id: str = Field(min_length=1)
    seed: str = "default"
    owner_id: str = Field(min_length=1)


class OwnershipRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str
    actor_id: str


class CompileRuleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: str = Field(min_length=1)
    document: RuleDocument
    state: dict[str, object] = Field(default_factory=dict)
    entity_id: str | None = None
    component: str | None = None


class LifecycleCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: str = Field(min_length=1)
    build: CharacterBuild
    resources: dict[str, ResourcePool] = Field(default_factory=dict)


class LevelUpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: str = Field(min_length=1)
    to_level: int = Field(ge=2)
    hit_point_gain: int = Field(default=0, ge=0)
    features: tuple[str, ...] = ()
    ability_points: int = Field(default=0, ge=0)


class RestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: str = Field(min_length=1)
    kind: str


class StudioPublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    package_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    engine_constraint: str = ">=3.0.0,<4.0.0"
    dependencies: tuple[PackageDependency, ...] = ()


def create_app(
    service: CampaignService | None = None,
    studio_service: StudioService | None = None,
    distribution: ContentDistributionRegistry | None = None,
) -> FastAPI:
    campaigns = service or CampaignService()
    studio = studio_service or StudioService()
    packages = distribution or ContentDistributionRegistry(engine_version="3.0.0")
    compiler = RuleCompiler()
    director = AdvancedAIDirector()
    app = FastAPI(title="rpg-engine-dnd", version=ENGINE_API_VERSION)

    async def runtime_or_404(campaign_id: str) -> CampaignRuntime:
        try:
            return await campaigns.get(campaign_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="campaign not found") from exc

    def require_owner(runtime: CampaignRuntime, owner_id: str | None) -> None:
        if not runtime.is_owner(owner_id):
            raise HTTPException(status_code=403, detail="campaign owner access required")

    @app.get("/", response_class=HTMLResponse)
    async def browser_client() -> str:
        return BROWSER_HTML

    @app.get("/health")
    async def health() -> dict[str, object]:
        return {"status": "ok", **PUBLIC_API_INFO}

    @app.post("/v3/campaigns")
    async def create_campaign(request: CreateCampaignRequest) -> dict[str, object]:
        try:
            await campaigns.create(request.campaign_id, request.seed, request.owner_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"campaign_id": request.campaign_id, "api_version": ENGINE_API_VERSION}

    @app.get("/v3/campaigns/{campaign_id}")
    async def get_campaign(
        campaign_id: str,
        actor_id: str | None = Query(default=None),
        x_user_id: str | None = Header(default=None),
        x_owner_id: str | None = Header(default=None),
    ) -> dict[str, object]:
        runtime = await runtime_or_404(campaign_id)
        async with runtime.lock:
            return runtime.view(user_id=x_user_id, actor_id=actor_id, owner_id=x_owner_id).model_dump(mode="json")

    @app.post("/v3/campaigns/{campaign_id}/ownership")
    async def assign_ownership(
        campaign_id: str,
        request: OwnershipRequest,
        x_owner_id: str | None = Header(default=None),
    ) -> dict[str, object]:
        runtime = await runtime_or_404(campaign_id)
        require_owner(runtime, x_owner_id)
        async with runtime.lock:
            runtime.actor_owners[request.actor_id] = request.user_id
            entity = runtime.engine.world.entities.get(request.actor_id)
            if entity is not None:
                runtime.knowledge.ingest_perception(request.actor_id, entity, sequence=runtime.engine.world.revision)
        return {"actor_id": request.actor_id, "user_id": request.user_id}

    @app.post("/v3/campaigns/{campaign_id}/perception/{actor_id}/{entity_id}")
    async def grant_perception(
        campaign_id: str,
        actor_id: str,
        entity_id: str,
        x_owner_id: str | None = Header(default=None),
    ) -> dict[str, object]:
        runtime = await runtime_or_404(campaign_id)
        require_owner(runtime, x_owner_id)
        async with runtime.lock:
            entity = runtime.engine.world.entity(entity_id)
            known = runtime.knowledge.ingest_perception(actor_id, entity, sequence=runtime.engine.world.revision)
        return known.model_dump(mode="json")

    @app.post("/v3/campaigns/{campaign_id}/commands")
    async def submit_command(
        campaign_id: str,
        request: dict[str, Any],
        x_owner_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        runtime = await runtime_or_404(campaign_id)
        require_owner(runtime, x_owner_id)
        try:
            event = await runtime.command(request)
            return event.model_dump(mode="json")
        except (ValueError, TypeError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v3/campaigns/{campaign_id}/events")
    async def event_history(
        campaign_id: str,
        after: int = Query(default=0, ge=0),
        actor_id: str | None = Query(default=None),
        x_user_id: str | None = Header(default=None),
        x_owner_id: str | None = Header(default=None),
    ) -> list[dict[str, object]]:
        runtime = await runtime_or_404(campaign_id)
        async with runtime.lock:
            events = [event for event in runtime.event_history if event.sequence > after]
            scoped = [runtime.scope_event(event, user_id=x_user_id, actor_id=actor_id, owner_id=x_owner_id) for event in events]
        return [event.model_dump(mode="json") for event in scoped if event is not None]

    @app.websocket("/v3/campaigns/{campaign_id}/events")
    async def event_socket(websocket: WebSocket, campaign_id: str) -> None:
        await websocket.accept()
        try:
            runtime = await campaigns.get(campaign_id)
        except KeyError:
            await websocket.close(code=4404)
            return
        actor_id = websocket.query_params.get("actor_id")
        user_id = websocket.headers.get("x-user-id")
        owner_id = websocket.headers.get("x-owner-id")
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=256)
        async with runtime.lock:
            runtime.subscribers.add(queue)
        try:
            while True:
                event = await queue.get()
                scoped = runtime.scope_event(event, user_id=user_id, actor_id=actor_id, owner_id=owner_id)
                if scoped is not None:
                    await websocket.send_json(scoped.model_dump(mode="json"))
        except WebSocketDisconnect:
            pass
        finally:
            async with runtime.lock:
                runtime.subscribers.discard(queue)

    @app.post("/v3/campaigns/{campaign_id}/actors/{actor_id}/lifecycle")
    async def create_lifecycle(
        campaign_id: str,
        actor_id: str,
        request: LifecycleCreateRequest,
        x_owner_id: str | None = Header(default=None),
    ) -> dict[str, object]:
        runtime = await runtime_or_404(campaign_id)
        require_owner(runtime, x_owner_id)
        if request.build.character_id != actor_id:
            raise HTTPException(status_code=400, detail="character id must match actor id")
        lifecycle = CharacterLifecycle(
            build=request.build,
            resources=request.resources,
        )
        event, _ = await runtime.mutate_component(
            entity_id=actor_id,
            component="lifecycle",
            command_id=request.command_id,
            mutator=lambda _: lifecycle.model_dump(mode="json"),
        )
        return {"event": event.model_dump(mode="json"), "lifecycle": lifecycle.model_dump(mode="json")}

    @app.post("/v3/campaigns/{campaign_id}/actors/{actor_id}/level-up")
    async def level_up(
        campaign_id: str,
        actor_id: str,
        request: LevelUpRequest,
        x_owner_id: str | None = Header(default=None),
    ) -> dict[str, object]:
        runtime = await runtime_or_404(campaign_id)
        require_owner(runtime, x_owner_id)
        outcome_holder: dict[str, object] = {}

        def mutate(raw: dict[str, Any]) -> dict[str, Any]:
            if not raw:
                raise ValueError("character lifecycle is not initialized")
            lifecycle = CharacterLifecycle.model_validate(raw)
            outcome = ProgressionTrack().advance(
                lifecycle.progression,
                to_level=request.to_level,
                hit_point_gain=request.hit_point_gain,
                features=request.features,
                ability_points=request.ability_points,
            )
            outcome_holder.update(outcome.model_dump(mode="json"))
            return lifecycle.model_dump(mode="json")

        try:
            event, value = await runtime.mutate_component(
                entity_id=actor_id,
                component="lifecycle",
                command_id=request.command_id,
                mutator=mutate,
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"event": event.model_dump(mode="json"), "outcome": outcome_holder, "lifecycle": value}

    @app.post("/v3/campaigns/{campaign_id}/actors/{actor_id}/rest")
    async def rest_actor(
        campaign_id: str,
        actor_id: str,
        request: RestRequest,
        x_owner_id: str | None = Header(default=None),
    ) -> dict[str, object]:
        runtime = await runtime_or_404(campaign_id)
        require_owner(runtime, x_owner_id)

        def mutate(raw: dict[str, Any]) -> dict[str, Any]:
            if not raw:
                raise ValueError("character lifecycle is not initialized")
            lifecycle = CharacterLifecycle.model_validate(raw)
            lifecycle.rest(request.kind)
            return lifecycle.model_dump(mode="json")

        try:
            event, value = await runtime.mutate_component(
                entity_id=actor_id,
                component="lifecycle",
                command_id=request.command_id,
                mutator=mutate,
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"event": event.model_dump(mode="json"), "lifecycle": value}

    @app.post("/v3/campaigns/{campaign_id}/scenes")
    async def register_scene(
        campaign_id: str,
        scene: Scene,
        x_owner_id: str | None = Header(default=None),
    ) -> dict[str, object]:
        runtime = await runtime_or_404(campaign_id)
        require_owner(runtime, x_owner_id)
        async with runtime.lock:
            runtime.orchestrator.register(scene)
        return scene.model_dump(mode="json")

    @app.post("/v3/campaigns/{campaign_id}/scenes/{scene_id}/{status}")
    async def transition_scene(
        campaign_id: str,
        scene_id: str,
        status: SceneStatus,
        x_owner_id: str | None = Header(default=None),
    ) -> dict[str, object]:
        runtime = await runtime_or_404(campaign_id)
        require_owner(runtime, x_owner_id)
        async with runtime.lock:
            scene = runtime.orchestrator.transition(scene_id, status)
        return scene.model_dump(mode="json")

    @app.post("/v3/campaigns/{campaign_id}/director/proposals")
    async def director_proposals(
        campaign_id: str,
        observation: DirectorObservation,
        x_owner_id: str | None = Header(default=None),
    ) -> list[dict[str, object]]:
        runtime = await runtime_or_404(campaign_id)
        require_owner(runtime, x_owner_id)
        if observation.campaign_id != campaign_id:
            raise HTTPException(status_code=400, detail="observation campaign mismatch")
        return [proposal.model_dump(mode="json") for proposal in director.propose(observation)]

    @app.post("/v3/campaigns/{campaign_id}/rules/execute")
    async def execute_rule(
        campaign_id: str,
        request: CompileRuleRequest,
        x_owner_id: str | None = Header(default=None),
    ) -> dict[str, object]:
        runtime = await runtime_or_404(campaign_id)
        require_owner(runtime, x_owner_id)
        try:
            _, result = await runtime.execute_rule(
                RuleExecuteCommand(
                    command_id=request.command_id,
                    document=request.document,
                    state=request.state,
                    entity_id=request.entity_id,
                    component=request.component,
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return result

    @app.post("/v3/studio/projects")
    async def put_project(project: StudioProject) -> dict[str, object]:
        return (await studio.put(project)).model_dump(mode="json")

    @app.get("/v3/studio/projects/{project_id}")
    async def get_project(project_id: str) -> dict[str, object]:
        try:
            return (await studio.get(project_id)).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="studio project not found") from exc

    @app.post("/v3/studio/projects/{project_id}/snapshot")
    async def snapshot_project(project_id: str) -> dict[str, object]:
        try:
            return (await studio.mutate_snapshot(project_id)).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="studio project not found") from exc

    @app.post("/v3/studio/rules/compile")
    async def compile_rule(document: RuleDocument) -> dict[str, object]:
        return compiler.compile(document).model_dump(mode="json")

    @app.post("/v3/studio/projects/{project_id}/publish")
    async def publish_project(project_id: str, request: StudioPublishRequest) -> dict[str, object]:
        try:
            project = await studio.get(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="studio project not found") from exc
        release = PackageRelease(
            package_id=request.package_id,
            version=request.version,
            engine_constraint=request.engine_constraint,
            dependencies=request.dependencies,
            content_hash=canonical_hash(project.document),
            metadata={
                "studio_project_id": project.project_id,
                "studio_revision_count": len(project.revisions),
            },
        )
        try:
            await packages.publish(release)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return release.model_dump(mode="json")

    @app.post("/v3/distribution/releases")
    async def publish_release(release: PackageRelease) -> dict[str, object]:
        try:
            await packages.publish(release)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return release.model_dump(mode="json")

    @app.get("/v3/distribution/resolve/{package_id}")
    async def resolve_release(package_id: str, constraint: str = Query(default="*")) -> dict[str, object]:
        try:
            return (await packages.resolve(package_id, constraint)).model_dump(mode="json")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app


app = create_app()
