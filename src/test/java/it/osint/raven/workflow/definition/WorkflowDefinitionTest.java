package it.osint.raven.workflow.definition;

import it.osint.raven.workflow.WorkflowCapability;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.lang.module.ModuleDescriptor.Version;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class WorkflowDefinitionTest {

    @TempDir
    private Path tempDir;

    @Test
    void loadsSimpleYamlDefinitionWithGoalNamesOnly() {
        WorkflowDefinition definition = WorkflowDefinition.load("""
                workflow:
                  id: libya-observer
                  version: 1.0
                goals:
                  - metadata
                  - entities
                  - claims
                  - assessment
                """);

        assertEquals("libya-observer", definition.id());
        assertEquals(Version.parse("1.0"), definition.version());
        assertEquals(List.of("metadata", "entities", "claims", "assessment"), definition.goals().stream()
                .map(goal -> goal.capability().id())
                .toList());
        assertTrue(definition.goals().stream().allMatch(WorkflowGoal::required));
        assertEquals(List.of(1, 2, 3, 4), definition.goals().stream().map(WorkflowGoal::priority).toList());
        assertEquals(Object.class, definition.goals().getFirst().capability().type());
    }

    @Test
    void supportsExtendedWorkflowAndGoalMetadata() {
        WorkflowDefinition definition = WorkflowDefinition.load("""
                workflow:
                  id: graph-export
                  name: Graph Export
                  description: Export enriched article to graph
                  version: 2.1.0
                configuration:
                  dry_run: true
                metadata:
                  owner: osint-team
                goals:
                  - id: neo4j
                    namespace: graph
                    description: Persist graph projection
                    version: 1.2.0
                    required: false
                    priority: 50
                """);

        WorkflowGoal goal = definition.goals().getFirst();

        assertEquals("Graph Export", definition.name());
        assertEquals("Export enriched article to graph", definition.description());
        assertEquals(Map.of("dry_run", true), definition.configuration());
        assertEquals(Map.of("owner", "osint-team"), definition.metadata());
        assertEquals("graph", goal.capability().namespace());
        assertEquals("neo4j", goal.capability().id());
        assertEquals("Persist graph projection", goal.capability().description());
        assertEquals(Version.parse("1.2.0"), goal.capability().version());
        assertFalse(goal.required());
        assertEquals(50, goal.priority());
    }

    @Test
    void savesAndLoadsYamlFile() throws IOException {
        WorkflowDefinition definition = new WorkflowDefinition(
                "libya-observer",
                "Libya Observer",
                "Extract intelligence artifacts",
                Version.parse("1.0"),
                List.of(WorkflowGoal.required("metadata"), WorkflowGoal.required("entities")),
                Map.of("profile", "default"),
                Map.of("owner", "analyst")
        );
        Path path = tempDir.resolve("workflow.yaml");

        definition.save(path);
        WorkflowDefinition loaded = WorkflowDefinition.load(path);

        assertTrue(Files.exists(path));
        assertEquals(definition.id(), loaded.id());
        assertEquals(definition.version(), loaded.version());
        assertEquals(definition.goals(), loaded.goals());
        assertEquals(definition.configuration(), loaded.configuration());
        assertEquals(definition.metadata(), loaded.metadata());
    }

    @Test
    void validateRejectsDuplicateGoals() {
        WorkflowDefinition definition = new WorkflowDefinition(
                "duplicate-goals",
                "",
                "",
                Version.parse("1.0"),
                List.of(WorkflowGoal.required("metadata"), WorkflowGoal.required("metadata")),
                Map.of(),
                Map.of()
        );

        assertThrows(IllegalArgumentException.class, definition::validate);
    }

    @Test
    void validateRejectsMissingIdAndNullGoal() {
        WorkflowDefinition missingId = new WorkflowDefinition(
                " ",
                "",
                "",
                Version.parse("1.0"),
                List.of(),
                Map.of(),
                Map.of()
        );
        WorkflowDefinition nullGoal = new WorkflowDefinition(
                "null-goal",
                "",
                "",
                Version.parse("1.0"),
                listWithNullGoal(),
                Map.of(),
                Map.of()
        );

        assertThrows(IllegalArgumentException.class, missingId::validate);
        assertThrows(IllegalArgumentException.class, nullGoal::validate);
    }

    @Test
    void loadRejectsInvalidVersionAndNullGoal() {
        assertThrows(IllegalArgumentException.class, () -> WorkflowDefinition.load("""
                workflow:
                  id: invalid-version
                  version: "@"
                goals:
                  - metadata
                """));

        assertThrows(IllegalArgumentException.class, () -> WorkflowDefinition.load("""
                workflow:
                  id: null-goal
                  version: 1.0
                goals:
                  -
                """));

        assertThrows(IllegalArgumentException.class, () -> WorkflowDefinition.load("""
                workflow:
                  id: missing-version
                goals:
                  - metadata
                """));
    }

    @Test
    void workflowGoalValidatesCapabilityAndPriority() {
        WorkflowCapability capability = WorkflowCapability.produced("metadata", Object.class);
        WorkflowGoal goal = WorkflowGoal.of(capability, true, 10);

        assertEquals(goal, goal.validate());
        assertThrows(NullPointerException.class, () -> WorkflowGoal.of(null, true, 10));
        assertThrows(IllegalArgumentException.class, () -> WorkflowGoal.of(capability, true, -1).validate());
    }

    private static List<WorkflowGoal> listWithNullGoal() {
        java.util.ArrayList<WorkflowGoal> goals = new java.util.ArrayList<>();
        goals.add(null);
        return goals;
    }
}
