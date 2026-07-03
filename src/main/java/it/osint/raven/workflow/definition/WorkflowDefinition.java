package it.osint.raven.workflow.definition;

import org.yaml.snakeyaml.DumperOptions;
import org.yaml.snakeyaml.Yaml;

import java.io.IOException;
import java.io.Reader;
import java.io.Serializable;
import java.io.StringReader;
import java.io.StringWriter;
import java.io.Writer;
import java.lang.module.ModuleDescriptor.Version;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/**
 * Immutable domain description of a Raven workflow.
 * <p>
 * A workflow definition describes what the workflow is expected to achieve,
 * not how to execute it. It deliberately does not describe a DAG, does not
 * list workflow nodes and does not reference LangGraph4j. The future compiler
 * will use this definition, the {@code WorkflowRegistry}, and registered node
 * capabilities to build an executable graph later.
 *
 * @param id stable workflow definition id
 * @param name human-readable workflow name
 * @param description short workflow description
 * @param version workflow definition version
 * @param goals ordered workflow goals
 * @param configuration safe workflow configuration metadata
 * @param metadata additional safe descriptive metadata
 */
public record WorkflowDefinition(
        String id,
        String name,
        String description,
        Version version,
        List<WorkflowGoal> goals,
        Map<String, Object> configuration,
        Map<String, Object> metadata
) implements Serializable {

    /**
     * Creates an immutable workflow definition and normalizes optional fields.
     */
    public WorkflowDefinition {
        id = normalizeText(id);
        name = name == null ? "" : name.trim();
        description = description == null ? "" : description.trim();
        version = version;
        goals = goals == null ? List.of() : Collections.unmodifiableList(new ArrayList<>(goals));
        configuration = immutableMap(configuration);
        metadata = immutableMap(metadata);
    }

    /**
     * Loads a workflow definition from a YAML file.
     *
     * @param path YAML file path
     * @return workflow definition
     * @throws IOException when the file cannot be read
     */
    public static WorkflowDefinition load(Path path) throws IOException {
        try (Reader reader = Files.newBufferedReader(path)) {
            return load(reader);
        }
    }

    /**
     * Loads a workflow definition from YAML text.
     *
     * @param yaml YAML document
     * @return workflow definition
     */
    public static WorkflowDefinition load(String yaml) {
        return load(new StringReader(Objects.requireNonNull(yaml, "yaml must not be null")));
    }

    /**
     * Loads a workflow definition from a reader.
     *
     * @param reader YAML reader
     * @return workflow definition
     */
    public static WorkflowDefinition load(Reader reader) {
        Objects.requireNonNull(reader, "reader must not be null");
        Object loaded = new Yaml().load(reader);
        if (!(loaded instanceof Map<?, ?> root)) {
            throw new IllegalArgumentException("workflow definition YAML must be a map");
        }
        WorkflowDefinition definition = fromMap(root);
        return definition.validate();
    }

    /**
     * Saves this workflow definition to a YAML file.
     *
     * @param path output path
     * @throws IOException when the file cannot be written
     */
    public void save(Path path) throws IOException {
        try (Writer writer = Files.newBufferedWriter(path)) {
            save(writer);
        }
    }

    /**
     * Writes this workflow definition as YAML.
     *
     * @param writer target writer
     */
    public void save(Writer writer) {
        Objects.requireNonNull(writer, "writer must not be null");
        yaml().dump(toYamlMap(), writer);
    }

    /**
     * Renders this workflow definition as YAML.
     *
     * @return YAML text
     */
    public String toYaml() {
        StringWriter writer = new StringWriter();
        save(writer);
        return writer.toString();
    }

    /**
     * Validates workflow definition invariants.
     * <p>
     * Validation checks id, version, null goals and duplicated goal
     * capabilities. It does not check node availability and does not build a
     * DAG; that work belongs to the future compiler.
     *
     * @return this definition when valid
     * @throws IllegalArgumentException when the definition is invalid
     */
    public WorkflowDefinition validate() {
        if (id == null || id.isBlank()) {
            throw new IllegalArgumentException("workflow id must not be blank");
        }
        if (version == null) {
            throw new IllegalArgumentException("workflow version must not be null");
        }
        Set<String> seen = new LinkedHashSet<>();
        for (WorkflowGoal goal : goals) {
            if (goal == null) {
                throw new IllegalArgumentException("workflow goal must not be null");
            }
            goal.validate();
            String key = goal.capability().qualifiedName();
            if (!seen.add(key)) {
                throw new IllegalArgumentException("duplicate workflow goal: " + key);
            }
        }
        return this;
    }

    private static WorkflowDefinition fromMap(Map<?, ?> root) {
        Map<?, ?> workflow = asMap(root.get("workflow"), "workflow");
        String id = asString(workflow.get("id"));
        String name = asString(workflow.get("name"));
        String description = asString(workflow.get("description"));
        Version version = parseVersion(workflow.get("version"));
        List<WorkflowGoal> goals = parseGoals(root.get("goals"));
        Map<String, Object> configuration = mergeMaps(root.get("configuration"), workflow.get("configuration"));
        Map<String, Object> metadata = mergeMaps(root.get("metadata"), workflow.get("metadata"));
        return new WorkflowDefinition(id, name, description, version, goals, configuration, metadata);
    }

    private Map<String, Object> toYamlMap() {
        Map<String, Object> root = new LinkedHashMap<>();
        Map<String, Object> workflow = new LinkedHashMap<>();
        workflow.put("id", id);
        if (!name.isBlank()) {
            workflow.put("name", name);
        }
        if (!description.isBlank()) {
            workflow.put("description", description);
        }
        workflow.put("version", version.toString());
        root.put("workflow", workflow);
        List<Object> yamlGoals = new ArrayList<>();
        for (int index = 0; index < goals.size(); index++) {
            yamlGoals.add(goals.get(index).toYamlValue(index + 1));
        }
        root.put("goals", yamlGoals);
        if (!configuration.isEmpty()) {
            root.put("configuration", configuration);
        }
        if (!metadata.isEmpty()) {
            root.put("metadata", metadata);
        }
        return root;
    }

    private static List<WorkflowGoal> parseGoals(Object value) {
        if (value == null) {
            return List.of();
        }
        if (!(value instanceof List<?> values)) {
            throw new IllegalArgumentException("goals must be a list");
        }
        List<WorkflowGoal> goals = new ArrayList<>();
        int priority = 1;
        for (Object item : values) {
            if (item == null) {
                throw new IllegalArgumentException("workflow goal must not be null");
            }
            goals.add(WorkflowGoal.fromYamlValue(item, priority++));
        }
        return List.copyOf(goals);
    }

    private static Version parseVersion(Object value) {
        if (value == null) {
            throw new IllegalArgumentException("workflow version must not be null");
        }
        String version = asString(value);
        if (version == null || version.isBlank()) {
            throw new IllegalArgumentException("workflow version must not be blank");
        }
        try {
            return Version.parse(version);
        } catch (IllegalArgumentException ex) {
            throw new IllegalArgumentException("invalid workflow version: " + version, ex);
        }
    }

    private static Map<?, ?> asMap(Object value, String field) {
        if (value instanceof Map<?, ?> map) {
            return map;
        }
        throw new IllegalArgumentException(field + " must be a map");
    }

    private static String asString(Object value) {
        return value == null ? null : String.valueOf(value);
    }

    private static Map<String, Object> mergeMaps(Object topLevel, Object nested) {
        Map<String, Object> values = new LinkedHashMap<>();
        values.putAll(copyMap(nested));
        values.putAll(copyMap(topLevel));
        return Map.copyOf(values);
    }

    private static Map<String, Object> copyMap(Object value) {
        if (value == null) {
            return Map.of();
        }
        if (!(value instanceof Map<?, ?> map)) {
            throw new IllegalArgumentException("configuration and metadata must be maps");
        }
        Map<String, Object> copy = new LinkedHashMap<>();
        map.forEach((key, mapValue) -> copy.put(String.valueOf(key), mapValue));
        return copy;
    }

    private static Map<String, Object> immutableMap(Map<String, Object> value) {
        return value == null || value.isEmpty() ? Map.of() : Map.copyOf(value);
    }

    private static String normalizeText(String value) {
        return value == null ? null : value.trim();
    }

    private static Yaml yaml() {
        DumperOptions options = new DumperOptions();
        options.setDefaultFlowStyle(DumperOptions.FlowStyle.BLOCK);
        options.setPrettyFlow(true);
        options.setIndent(2);
        return new Yaml(options);
    }
}
