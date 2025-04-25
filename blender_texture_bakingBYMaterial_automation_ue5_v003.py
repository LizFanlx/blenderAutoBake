import bpy
import os
from mathutils import Vector

class BakeConstants:
    TEXTURE_SIZE = 2048
    SAMPLES = 512
    BAKE_TYPES = {
        'DIFFUSE': 'diffuse',
        'NORMAL': 'normal',
        'ROUGHNESS': 'roughness',
        'AO': 'ao',
        'EMIT': 'metallic'  # no metallic in Blender, needs special processing
    }

# file management
class FileManager:
    @staticmethod
    def get_output_path():
        """get out put path"""
        blend_file_path = bpy.data.filepath
        if not blend_file_path:
            raise Exception("please save blender file")
        
        blend_dir = os.path.dirname(blend_file_path)
        output_path = os.path.join(blend_dir, "BakedTextures")
        
        if not os.path.exists(output_path):
            os.makedirs(output_path)
        return output_path

    @staticmethod
    def create_material_folder(material_name, output_path):
        """create material folder"""
        material_path = os.path.join(output_path, material_name)
        if not os.path.exists(material_path):
            os.makedirs(material_path)
        return material_path

# material management
class MaterialManager:
    @staticmethod
    def get_all_materials():
        """get all meterials"""
        materials = set()
        for obj in bpy.context.scene.objects:
            if obj.type == 'MESH':
                for slot in obj.material_slots:
                    if slot.material:
                        materials.add(slot.material)
        return list(materials)

    @staticmethod
    def get_uv_hash(obj, material):
        """Get the UV hash of a specific material of the object"""
        if not obj.data.uv_layers:
            return 'no_uv'
            
        uv_coords = []
        material_indices = {slot.material: i for i, slot in enumerate(obj.material_slots)}
        
        # check if the material exists in material indices
        if material not in material_indices:
            return 'material_not_found'
            
        # Collect only the UV coordinates of the faces using this material
        for poly in obj.data.polygons:
            # Check: Ensure the material index is within a valid range
            if poly.material_index < len(obj.material_slots):
                if obj.material_slots[poly.material_index].material == material:
                    for loop_idx in poly.loop_indices:
                        uv = obj.data.uv_layers.active.data[loop_idx].uv
                        uv_coords.append((round(uv.x, 4), round(uv.y, 4)))
        
        # Sort and generate a hash value
        uv_coords.sort()
        return hash(tuple(uv_coords)) if uv_coords else 'empty_uv'

    @staticmethod
    def duplicate_shared_materials():
        """detect and duplicate shared materials"""
        material_usage = {}
        
        # Pass 1: Group and count material usage based on UV layout
        for obj in bpy.context.scene.objects:
            if obj.type == 'MESH':
                for slot in obj.material_slots:
                    if slot.material:
                        try:
                            uv_hash = MaterialManager.get_uv_hash(obj, slot.material)
                            usage_key = (slot.material, uv_hash)
                            
                            if usage_key not in material_usage:
                                material_usage[usage_key] = []
                            material_usage[usage_key].append((obj, slot))
                        except Exception as e:
                            print(f"Processing material of {obj.name} Error: {str(e)}")
                            continue

        # Pass 2: Material processing
        for (original_material, uv_hash), usages in material_usage.items():
            if len(usages) > 1 and uv_hash not in ['no_uv', 'material_not_found', 'empty_uv']:
                print(f"\nMaterial '{original_material.name}' is used by multiple objects:")
                
                # If this is the first object using the material, rename the material by adding "_MASTER" to its name
                first_obj, first_slot = usages[0]
                master_material_name = f"{original_material.name}_MASTER_{first_obj.name}"
                original_material.name = master_material_name
                print(f"- {first_obj.name} uses the master material '{master_material_name}'")
                
                # For all other users
                for obj, slot in usages[1:]:
                    try:
                        current_uv_hash = MaterialManager.get_uv_hash(obj, slot.material)
                        
                        if current_uv_hash != uv_hash and current_uv_hash not in ['no_uv', 'material_not_found', 'empty_uv']:
                            # If the UV layout is DIFFERENT, create an instance of the material
                            new_material = original_material.copy()
                            new_material.name = f"{original_material.name}_INSTANCE_{obj.name}"
                            slot.material = new_material
                            print(f"- {obj.name} using material '{new_material.name}'")
                        else:
                            # If the UV layout is the SAME, continue using the original master material
                            print(f"- {obj.name} share master material '{master_material_name}'")
                    except Exception as e:
                        print(f"Proccessing the UV of {obj.name} Error: {str(e)}")
                        continue

    @staticmethod
    def cleanup_unused_materials():
        """Clean up unused materials"""
        for material in bpy.data.materials:
            if not material.users:
                bpy.data.materials.remove(material)

    @staticmethod
    def setup_bake_node(material):
        """Set up bake nodes"""
        material.use_nodes = True
        nodes = material.node_tree.nodes
        
        # Remove existing baking nodes
        existing = nodes.get('Bake_Target')
        if existing:
            nodes.remove(existing)
        
        # create new baking node
        bake_node = nodes.new('ShaderNodeTexImage')
        bake_node.name = 'Bake_Target'
        bake_node.select = True
        nodes.active = bake_node
        
        return bake_node

    @staticmethod
    def setup_metallic_nodes(material):
        """set up metallic nodes"""
        nodes = material.node_tree.nodes
        links = material.node_tree.links
        
        # save original links
        original_links = []
        for link in material.node_tree.links:
            original_links.append((link.from_socket, link.to_socket))
        
        # create emit nodes
        emit = nodes.new('ShaderNodeEmission')
        
        # get or create material output nodes
        output = nodes.get('Material Output')
        if not output:
            output = nodes.new('ShaderNodeOutputMaterial')
        
        # find Principled BSDF node
        principled = next((node for node in nodes if node.type == 'BSDF_PRINCIPLED'), None)
        if not principled:
            principled = nodes.new('ShaderNodeBsdfPrincipled')
        
        # link metallic to emit
        metallic_socket = principled.inputs['Metallic']
        if metallic_socket.is_linked:
            links.new(metallic_socket.links[0].from_socket, emit.inputs['Strength'])
        else:
            value = nodes.new('ShaderNodeValue')
            value.outputs[0].default_value = metallic_socket.default_value
            links.new(value.outputs[0], emit.inputs['Strength'])
        
        # link emit to output
        links.new(emit.outputs[0], output.inputs['Surface'])
        
        return original_links

    @staticmethod
    def restore_material_links(material, original_links):
        """restore material links"""
        nodes = material.node_tree.nodes
        links = material.node_tree.links
        
        # remove temporary nodes
        for node in nodes:
            if node.type in ['EMISSION', 'VALUE']:
                nodes.remove(node)
        
        # restore links
        for from_socket, to_socket in original_links:
            links.new(from_socket, to_socket)

# Bake setting class
class BakeSettings:
    @staticmethod
    def setup():
        scene = bpy.context.scene
        scene.render.engine = 'CYCLES'
        scene.cycles.samples = BakeConstants.SAMPLES
        BakeSettings._setup_gpu()
        BakeSettings._setup_performance(scene)
        scene.use_nodes = True

    @staticmethod
    def _setup_gpu():
        if not hasattr(bpy.context.preferences.addons['cycles'].preferences, 'get_devices_for_type'):
            return
        
        prefs = bpy.context.preferences
        cycles_prefs = prefs.addons['cycles'].preferences
        
        if hasattr(cycles_prefs, 'get_devices_for_type'):
            if cycles_prefs.get_devices_for_type('OPTIX'):
                bpy.context.scene.cycles.device = 'GPU'
                cycles_prefs.compute_device_type = 'OPTIX'
                print("use OptiX GPU")
            elif cycles_prefs.get_devices_for_type('CUDA'):
                bpy.context.scene.cycles.device = 'GPU'
                cycles_prefs.compute_device_type = 'CUDA'
                print("use CUDA GPU")
            else:
                bpy.context.scene.cycles.device = 'CPU'
                print("use CPU")

    @staticmethod
    def _setup_performance(scene):
        if hasattr(scene.cycles, 'tile_size'):
            scene.cycles.tile_size = 512
        elif hasattr(scene.render, 'tile_x'):
            scene.render.tile_x = scene.render.tile_y = 512

# Baking class
class TextureBaker:
    def __init__(self):
        self.file_manager = FileManager()
        self.material_manager = MaterialManager()

    def _create_bake_image(self, name):
        """create bake image"""
        # Check if an image with the same name already exists
        existing = bpy.data.images.get(name)
        if existing:
            bpy.data.images.remove(existing)
            
        image = bpy.data.images.new(
            name=name,
            width=BakeConstants.TEXTURE_SIZE,
            height=BakeConstants.TEXTURE_SIZE,
            alpha=True,
            float_buffer=True
        )
        return image

    def _save_baked_image(self, image, path, filename):
        """save baked image"""
        filepath = os.path.join(path, filename)
        image.save_render(filepath)
        print(f"save texture: {filepath}")

    def _bake_all_maps(self, material, bake_node, output_path):
        """bake all the maps"""
        for bake_type, suffix in BakeConstants.BAKE_TYPES.items():
            try:
                # naming convention: Extract object information from the material name
                material_parts = material.name.split('_')
                if len(material_parts) > 1:
                    # if it's a duplicated material
                    base_material_name = material_parts[0] 
                    object_name = "_".join(material_parts[1:]) 
                    map_name = f"{base_material_name}_{object_name}_{suffix}"
                else:
                    # if it's the original material
                    map_name = f"{material.name}_{suffix}"

                image = self._create_bake_image(map_name)
                bake_node.image = image
                
                original_links = None
                if suffix == 'metallic':
                    original_links = self.material_manager.setup_metallic_nodes(material)
                    bake_type = 'EMIT'
                
                try:
                    bpy.ops.object.bake(type=bake_type)
                    self._save_baked_image(image, output_path, f"{map_name}.png")
                finally:
                    if original_links:
                        self.material_manager.restore_material_links(material, original_links)
                
            except Exception as e:
                print(f"Baking {suffix} failed: {str(e)}")
                return False
        return True

    def bake_material(self, material, output_path):
        try:
            # create output folder for each material
            material_path = self.file_manager.create_material_folder(material.name, output_path)
            
            # Group objects that use the material based on their UV layout
            uv_groups = {}
            for obj in bpy.context.scene.objects:
                if obj.type == 'MESH':
                    if any(slot.material == material for slot in obj.material_slots):
                        uv_hash = self.material_manager.get_uv_hash(obj, material)
                        if uv_hash not in ['no_uv', 'material_not_found', 'empty_uv']:
                            if uv_hash not in uv_groups:
                                uv_groups[uv_hash] = []
                            uv_groups[uv_hash].append(obj)
            
            if not uv_groups:
                print(f"There are no objects assigned with this material: {material.name}")
                return False
            
            # Bake each UV group only once
            for uv_hash, objects in uv_groups.items():
                print(f"\proccessing objects in UV group {uv_hash} :")
                for obj in objects:
                    print(f"- {obj.name}")
                
                # Bake only the first object of each UV group
                bpy.ops.object.select_all(action='DESELECT')
                objects[0].select_set(True)
                bpy.context.view_layer.objects.active = objects[0]
                
                # set up baking nodes
                bake_node = self.material_manager.setup_bake_node(material)
                
                # execture baking proccess
                success = self._bake_all_maps(material, bake_node, material_path)
                if not success:
                    return False
            
            return True
            
        except Exception as e:
            print(f"Failed in baking material {material.name} : {str(e)}")
            return False

    def execute(self):
        """Execute the full baking process"""
        try:
            print("Start the baking proccess...")
            
            # First deal with shared materials
            print("\nChecking shared material...")
            self.material_manager.duplicate_shared_materials()
            
            # get output path
            output_path = self.file_manager.get_output_path()
            
            # baking set up
            BakeSettings.setup()
            
            # get all the materials
            materials = self.material_manager.get_all_materials()
            if not materials:
                raise Exception("No usable materials in the scene")
            
            # proccess all the materials
            success_count = 0
            for i, material in enumerate(materials, 1):
                print(f"\nProccing material {i}/{len(materials)}: {material.name}")
                if self.bake_material(material, output_path):
                    success_count += 1
            
            # clean up unused materials
            self.material_manager.cleanup_unused_materials()
            
            print(f"\n=== finished baking ===")
            print(f"success: {success_count}/{len(materials)} ")
            print(f"output path: {output_path}")
            
        except Exception as e:
            print(f"errer: {str(e)}")
            import traceback
            print(traceback.format_exc())

def main():
    baker = TextureBaker()
    baker.execute()

if __name__ == "__main__":
    main()
